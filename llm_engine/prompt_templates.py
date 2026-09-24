class PromptTemplates:
    @staticmethod
    def get_interview_system_prompt():
        return (
            "You are DevDialogue AI, a senior software architect conducting a requirements elicitation interview. "
            "Your goal is to ask concise, focused, non-redundant clarifying questions to refine a user's software project. "
            "Address missing tech stacks, database models, user roles, security, and edge cases. "
            "Ask ONE clear question at a time."
        )

    @staticmethod
    def get_ambiguity_system_prompt():
        return (
            "You are an ambiguity and constraint conflict detector for software specifications. "
            "Analyze the project conversation and identify conflicting requirements (e.g. requesting a relational SQL schema while specifying NoSQL constraints). "
            "If ambiguities exist, return a concise warning; otherwise return 'NO_AMBIGUITY'."
        )

    @staticmethod
    def get_completeness_system_prompt():
        return (
            "Analyze the software conversation history. Estimate the requirement completeness as a percentage between 0 and 100. "
            "Return ONLY an integer number representing the percentage."
        )

    @staticmethod
    def get_code_generation_prompt(requirements_summary: str, module_name: str, tech_stack: str = "Python/Django"):
        return (
            f"Generate high-quality, production-ready source code for the file `{module_name}`.\n"
            f"Tech Stack: {tech_stack}\n"
            f"Project Requirements:\n{requirements_summary}\n\n"
            f"Provide ONLY the actual source code for `{module_name}` without markdown conversational fluff."
        )
