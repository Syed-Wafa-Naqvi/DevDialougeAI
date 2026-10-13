import csv
import glob
import json
import os
import sys
import time
from datetime import timezone as dt_timezone
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.conf import settings
from django.utils import timezone
from django.db.models import Sum

from chat.models import Session
from generator.planner import PlanGenerator, PlanValidator
from generator.code_builder import CodeBuilder
from generator.verifier import StaticVerifier
from generator.repair import CodeRepairEngine
from generator.runtime_verifier import RuntimeVerifier
from llm_engine.models import LLMCallLog
from llm_engine.prompt_templates import PROMPT_VERSION

User = get_user_model()

class Command(BaseCommand):
    help = "Run non-interactive evaluation benchmarks across project specifications."

    def add_arguments(self, parser):
        parser.add_argument(
            '--specs',
            type=str,
            default='all',
            help='Comma-separated spec filenames (e.g., 01_todo_app,02_blog_engine) or "all".'
        )
        parser.add_argument(
            '--provider',
            type=str,
            default='mock',
            help='AI Provider to evaluate (mock, free, openai, gemini, etc.). Defaults to mock.'
        )
        parser.add_argument(
            '--runtime',
            action='store_true',
            help='Enable Phase 7 Lite Runtime Checks as part of evaluation.'
        )
        parser.add_argument(
            '--compare',
            type=str,
            default=None,
            help='Path to a previous benchmark result JSON file for comparison.'
        )

    def handle(self, *args, **options):
        specs_arg = options['specs']
        provider = options['provider']
        run_runtime = options['runtime']
        compare_path = options['compare']

        specs_dir = os.path.join(settings.BASE_DIR, 'benchmarks', 'specs')
        results_dir = os.path.join(settings.BASE_DIR, 'benchmarks', 'results')
        os.makedirs(specs_dir, exist_ok=True)
        os.makedirs(results_dir, exist_ok=True)

        # Spec File Selection
        all_spec_files = sorted(glob.glob(os.path.join(specs_dir, '*.md')))
        if not all_spec_files:
            self.stdout.write(self.style.ERROR(f"No benchmark spec files (.md) found in {specs_dir}"))
            return

        target_files = []
        if specs_arg == 'all':
            target_files = all_spec_files
        else:
            selected_names = [s.strip().replace('.md', '') for s in specs_arg.split(',')]
            for sf in all_spec_files:
                basename = os.path.basename(sf).replace('.md', '')
                if any(sel in basename for sel in selected_names):
                    target_files.append(sf)

        if not target_files:
            self.stdout.write(self.style.ERROR(f"No spec files matched selection '{specs_arg}'."))
            return

        self.stdout.write(self.style.SUCCESS(
            f"\n🚀 Running DevDialogue AI Evaluation Benchmark [{len(target_files)} specs | Provider: {provider} | Prompt: {PROMPT_VERSION}]"
        ))
        self.stdout.write("=" * 85)

        # Get/Create Benchmark Runner User
        runner_user, _ = User.objects.get_or_create(
            username='benchmark_runner',
            defaults={'email': 'benchmark@devdialogue.ai', 'is_staff': True, 'is_active': True}
        )

        results = []
        start_timestamp = timezone.now().strftime('%Y%m%d_%H%M%S')

        for spec_path in target_files:
            spec_filename = os.path.basename(spec_path)
            spec_name = os.path.splitext(spec_filename)[0]

            with open(spec_path, 'r', encoding='utf-8') as f:
                spec_content = f.read()

            self.stdout.write(f"\n📋 Benchmark Spec: {spec_filename}")

            session = Session.objects.create(
                user=runner_user,
                title=f"Benchmark Run - {spec_name}",
                mode='mode1',
                status='active'
            )

            spec_start_t = time.time()
            plan_valid = False
            plan_attempts = 1
            plan_data = None
            generated_files = {}

            # 1. Plan Elicitation & Generation
            try:
                plan_obj = PlanGenerator.generate_plan(srs_summary=spec_content, session=session, provider_name=provider)
                if plan_obj:
                    plan_obj.status = 'approved'
                    plan_obj.save(update_fields=['status'])
                    plan_valid = True
                    plan_data = plan_obj.plan_data
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"   ⚠️ Plan Generation Error: {str(e)}"))



            # 2. Code Generation
            modules_to_build = plan_data.get('modules', []) if plan_data else ['main.py']
            for mod in modules_to_build:
                mod_path = mod.get('path') if isinstance(mod, dict) else str(mod)
                code_text = CodeBuilder.generate_code_for_module(mod_path, spec_content, provider_name=provider)
                generated_files[mod_path] = code_text

            if not generated_files:
                generated_files['main.py'] = "# Benchmark dummy fallback\n"

            # 3. Initial Static Verification
            initial_verif = StaticVerifier.verify_project(generated_files, plan_data=plan_data)
            init_errors = initial_verif['error_count']
            init_warnings = initial_verif['warning_count']

            # 4. Automated Repair Loop
            repair_res = CodeRepairEngine.run_repair_loop(
                session=session,
                files_dict=generated_files,
                plan_data=plan_data,
                max_attempts=3,
                provider_name=provider
            )

            final_files = repair_res['files']
            repair_attempts = repair_res['attempts']
            final_status = repair_res['status']
            final_verif = repair_res['verification']

            # 5. Optional Lite Runtime Checks
            runtime_res = {'executed': False, 'passed': True, 'reason': 'Runtime checks not enabled'}
            if run_runtime:
                runtime_res = RuntimeVerifier.run_verification(final_files, user=runner_user, plan_data=plan_data)

            duration_s = round(time.time() - spec_start_t, 2)

            # 6. Usage Token Aggregation
            logs = LLMCallLog.objects.filter(session=session)
            token_agg = logs.aggregate(in_tot=Sum('input_tokens'), out_tot=Sum('output_tokens'))
            total_tokens = (token_agg['in_tot'] or 0) + (token_agg['out_tot'] or 0)
            estimated_cost = round(float(total_tokens) * 0.000002, 6)

            spec_metric = {
                'spec_name': spec_name,
                'filename': spec_filename,
                'plan_valid': plan_valid,
                'plan_attempts': plan_attempts,
                'file_count': len(final_files),
                'initial_errors': init_errors,
                'initial_warnings': init_warnings,
                'repaired_errors': final_verif['error_count'],
                'repaired_warnings': final_verif['warning_count'],
                'repair_attempts': repair_attempts,
                'final_status': final_status,
                'runtime_executed': runtime_res.get('executed', False),
                'runtime_passed': runtime_res.get('passed', True),
                'runtime_reason': runtime_res.get('reason', ''),
                'total_tokens': total_tokens,
                'estimated_cost': estimated_cost,
                'duration_seconds': duration_s,
                'provider': provider,
                'prompt_version': PROMPT_VERSION,
            }
            results.append(spec_metric)

            self.stdout.write(
                f"   Result: Status={final_status} | Files={len(final_files)} | InitErrors={init_errors} | "
                f"Repairs={repair_attempts} | Duration={duration_s}s | Tokens={total_tokens}"
            )

        # Output Artifacts
        json_path = os.path.join(results_dir, f"benchmark_{start_timestamp}.json")
        csv_path = os.path.join(results_dir, f"benchmark_{start_timestamp}.csv")

        summary_metrics = self._calculate_summary_metrics(results)
        output_payload = {
            'timestamp': start_timestamp,
            'provider': provider,
            'prompt_version': PROMPT_VERSION,
            'summary': summary_metrics,
            'results': results
        }

        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(output_payload, f, indent=2)

        self._write_csv_report(csv_path, results)

        self._print_summary_table(summary_metrics, json_path, csv_path)

        if compare_path:
            self._compare_results(compare_path, output_payload)

    def _calculate_summary_metrics(self, results: list) -> dict:
        total_specs = len(results)
        if total_specs == 0:
            return {}

        valid_plans = sum(1 for r in results if r['plan_valid'])
        first_pass_verified = sum(1 for r in results if r['initial_errors'] == 0)
        final_verified = sum(1 for r in results if r['final_status'] in ('verified', 'verified_with_warnings'))
        avg_repairs = round(sum(r['repair_attempts'] for r in results) / total_specs, 2)
        avg_duration = round(sum(r['duration_seconds'] for r in results) / total_specs, 2)
        avg_tokens = round(sum(r['total_tokens'] for r in results) / total_specs, 2)
        avg_cost = round(sum(r['estimated_cost'] for r in results) / total_specs, 6)

        return {
            'total_specs': total_specs,
            'valid_plans_pct': round((valid_plans / total_specs) * 100, 1),
            'first_pass_verified_pct': round((first_pass_verified / total_specs) * 100, 1),
            'final_verified_pct': round((final_verified / total_specs) * 100, 1),
            'avg_repair_attempts': avg_repairs,
            'avg_duration_seconds': avg_duration,
            'avg_total_tokens': avg_tokens,
            'avg_estimated_cost': avg_cost,
        }

    def _write_csv_report(self, csv_path: str, results: list):
        if not results:
            return
        fieldnames = list(results[0].keys())
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)

    def _print_summary_table(self, summary: dict, json_path: str, csv_path: str):
        self.stdout.write("\n" + "=" * 85)
        self.stdout.write(self.style.SUCCESS("📊 BENCHMARK EVALUATION SUMMARY METRICS"))
        self.stdout.write("=" * 85)
        self.stdout.write(f"  • Total Specifications Evaluated:  {summary.get('total_specs')}")
        self.stdout.write(f"  • Valid Architecture Plans (%):   {summary.get('valid_plans_pct')}%")
        self.stdout.write(f"  • First-Pass Verified (%):         {summary.get('first_pass_verified_pct')}%")
        self.stdout.write(f"  • Final Verified after Repair (%):  {summary.get('final_verified_pct')}%")
        self.stdout.write(f"  • Average Repair Attempts:        {summary.get('avg_repair_attempts')}")
        self.stdout.write(f"  • Average Execution Duration:     {summary.get('avg_duration_seconds')} s")
        self.stdout.write(f"  • Average Token Consumption:       {summary.get('avg_total_tokens')} tokens")
        self.stdout.write(f"  • Average Estimated Cost:         ${summary.get('avg_estimated_cost')}")
        self.stdout.write("=" * 85)
        self.stdout.write(f"📄 Saved JSON: {json_path}")
        self.stdout.write(f"📊 Saved CSV:  {csv_path}\n")

    def _compare_results(self, baseline_path: str, current_payload: dict):
        if not os.path.exists(baseline_path):
            self.stdout.write(self.style.ERROR(f"Comparison baseline file not found: {baseline_path}"))
            return

        with open(baseline_path, 'r', encoding='utf-8') as f:
            baseline = json.load(f)

        base_results = {r['spec_name']: r for r in baseline.get('results', [])}
        curr_results = {r['spec_name']: r for r in current_payload.get('results', [])}

        self.stdout.write("\n" + "=" * 85)
        self.stdout.write(self.style.SUCCESS(f"📈 COMPARISON WITH BASELINE [{os.path.basename(baseline_path)}]"))
        self.stdout.write("=" * 85)
        self.stdout.write(f"{'Spec Name':<28} | {'Baseline Status':<16} | {'Current Status':<16} | {'Delta':<12}")
        self.stdout.write("-" * 85)

        for spec_name, curr_r in curr_results.items():
            base_r = base_results.get(spec_name)
            if not base_r:
                delta = "🆕 NEW"
                base_status = "N/A"
            else:
                base_status = base_r.get('final_status', 'unknown')
                curr_status = curr_r.get('final_status', 'unknown')

                if base_status != curr_status and curr_status in ('verified', 'verified_with_warnings'):
                    delta = "✅ IMPROVED"
                elif base_status in ('verified', 'verified_with_warnings') and curr_status == 'needs_attention':
                    delta = "⚠️ REGRESSED"
                elif curr_r['repaired_errors'] < base_r['repaired_errors']:
                    delta = "✅ IMPROVED"
                elif curr_r['repaired_errors'] > base_r['repaired_errors']:
                    delta = "⚠️ REGRESSED"
                else:
                    delta = "➡️ UNCHANGED"

            self.stdout.write(f"{spec_name:<28} | {base_status:<16} | {curr_r['final_status']:<16} | {delta:<12}")

        self.stdout.write("=" * 85 + "\n")
