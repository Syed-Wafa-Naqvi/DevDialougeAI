#!/usr/bin/env python3
"""
DevDialogue AI — WCAG Contrast Check Script (§3.4)
Verifies contrast ratios for Studio Light & Dim theme color tokens.
"""

import sys

def hex_to_relative_luminance(hex_str):
    hex_str = hex_str.lstrip('#')
    if len(hex_str) == 3:
        hex_str = ''.join([c*2 for c in hex_str])
    r, g, b = [int(hex_str[i:i+2], 16) / 255.0 for i in (0, 2, 4)]
    
    def adjust(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r_adj, g_adj, b_adj = adjust(r), adjust(g), adjust(b)
    return 0.2126 * r_adj + 0.7152 * g_adj + 0.0722 * b_adj

def contrast_ratio(hex1, hex2):
    lum1 = hex_to_relative_luminance(hex1)
    lum2 = hex_to_relative_luminance(hex2)
    brighter = max(lum1, lum2)
    darker = min(lum1, lum2)
    return (brighter + 0.05) / (darker + 0.05)

def check_all_pairs():
    # Studio Light Tokens (§3.1)
    light_tokens = {
        "--canvas": "#F6F7F9",
        "--surface": "#FFFFFF",
        "--surface-sunken": "#EFF1F4",
        "--ink": "#0B1220",
        "--ink-2": "#374151",
        "--ink-3": "#5B6472",
        "--brand": "#2548E8",
        "--brand-tint": "#EEF2FF",
        "--accent": "#FF6A2B",
        "--success-text": "#15803D",
        "--warning-text": "#A35C00",
        "--error-text": "#C62A30"
    }

    # Dim Dark Tokens (§3.2)
    dim_tokens = {
        "--canvas": "#16181D",
        "--surface": "#1E2128",
        "--surface-sunken": "#1A1C22",
        "--ink": "#F1F3F6",
        "--ink-2": "#C4C9D2",
        "--ink-3": "#9AA1AC",
        "--brand": "#7B95FF",
        "--brand-tint": "#1E2338",
        "--success-text": "#4ADE80",
        "--warning-text": "#FBBF24",
        "--error-text": "#F87171"
    }

    pairs_to_test = [
        ("Primary Text on Surface", "--ink", "--surface", 7.0),
        ("Secondary Text on Surface", "--ink-2", "--surface", 4.5),
        ("Tertiary Text on Surface", "--ink-3", "--surface", 4.5),
        ("Primary Text on Canvas", "--ink", "--canvas", 7.0),
        ("Brand Text on Surface", "--brand", "--surface", 4.5),
        ("Brand Text on Brand Tint", "--brand", "--brand-tint", 4.5),
        ("Success Text on Surface", "--success-text", "--surface", 4.5),
        ("Warning Text on Surface", "--warning-text", "--surface", 4.5),
        ("Error Text on Surface", "--error-text", "--surface", 4.5),
    ]

    print("=" * 70)
    print("📊 DevDialogue AI — Studio Light Contrast Audit")
    print("=" * 70)
    
    failed = False
    print("\n[Light Theme (Default)]")
    for name, text_key, bg_key, min_ratio in pairs_to_test:
        text_hex = light_tokens[text_key]
        bg_hex = light_tokens[bg_key]
        ratio = contrast_ratio(text_hex, bg_hex)
        status = "PASSED" if ratio >= min_ratio else "FAILED"
        print(f"  • {name:<30}: Ratio {ratio:.2f}:1 (Target >= {min_ratio}:1) -> [{status}]")
        if ratio < min_ratio:
            failed = True

    print("\n[Dim Theme (Optional)]")
    for name, text_key, bg_key, min_ratio in pairs_to_test:
        if text_key in dim_tokens and bg_key in dim_tokens:
            text_hex = dim_tokens[text_key]
            bg_hex = dim_tokens[bg_key]
            ratio = contrast_ratio(text_hex, bg_hex)
            status = "PASSED" if ratio >= min_ratio else "FAILED"
            print(f"  • {name:<30}: Ratio {ratio:.2f}:1 (Target >= {min_ratio}:1) -> [{status}]")
            if ratio < min_ratio:
                failed = True

    print("=" * 70)
    if failed:
        print("❌ Audit Failed: Some contrast ratios are below thresholds.")
        sys.exit(1)
    else:
        print("✅ Audit Passed: 100% of tested pairs meet WCAG AA/AAA targets!")
        sys.exit(0)

if __name__ == '__main__':
    check_all_pairs()
