from nano_claude.tool import Tool, ToolContext, ToolExecResult


class QuestionTool(Tool):
    @property
    def name(self) -> str:
        return "question"

    @property
    def description(self) -> str:
        return (
            "Ask the user for input to gather preferences, clarify ambiguous "
            "instructions, or get decisions on implementation choices. "
            "Each question can have multiple choice options. "
            "A 'Type your own answer' option is added automatically. "
            "Use this when you need user input to proceed."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "question": {
                                "type": "string",
                                "description": "The full question text to ask the user",
                            },
                            "header": {
                                "type": "string",
                                "description": "Short title for the question (max 30 chars)",
                            },
                            "options": {
                                "type": "array",
                                "description": "Predefined answer options (a custom answer option is added automatically)",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "label": {
                                            "type": "string",
                                            "description": "Short option label (1-5 words)",
                                        },
                                        "description": {
                                            "type": "string",
                                            "description": "Detailed option description",
                                        },
                                    },
                                    "required": ["label", "description"],
                                },
                            },
                            "multiple": {
                                "type": "boolean",
                                "description": "Whether multiple selections are allowed (default: false)",
                            },
                        },
                        "required": ["question", "header", "options"],
                    },
                },
            },
            "required": ["questions"],
        }

    async def execute(self, args: dict, ctx: ToolContext) -> ToolExecResult:
        questions = args["questions"]

        if ctx.ask_user_callback is None:
            return ToolExecResult(
                output="Error: Cannot ask user - no interactive input handler available. "
                       "Make educated guesses and proceed.",
                title="question [error]",
            )

        answers = []
        for q in questions:
            answer = await ctx.ask_user_callback(
                header=q.get("header", "Question"),
                question=q["question"],
                options=q.get("options", []),
                multiple=q.get("multiple", False),
            )
            answers.append({
                "question": q["question"],
                "answer": answer if answer else ["(unanswered)"],
            })

        formatted = "; ".join(
            f'"{a["question"]}" → {"、".join(a["answer"])}'
            for a in answers
        )

        return ToolExecResult(
            title=f"question [{len(questions)} answered]",
            output=f"User answers: {formatted}.",
        )
