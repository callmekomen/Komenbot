"""
Komen AI - Entry point.

Usage:
    python main.py                     # interactive mode
    python main.py "your task here"    # run a single task and exit
    python main.py --providers         # show which AI providers are configured
"""
import sys
import config
from agent import KomenAgent


def _no_providers_message():
    print("ERROR: No AI provider configured. Set at least one API key, e.g.:")
    print("  export KOMEN_PROVIDERS=groq,gemini,anthropic")
    print("  export GROQ_API_KEY=gsk_...")
    print("  export GEMINI_API_KEY=AIza...")
    print("  export ANTHROPIC_API_KEY=sk-ant-...")
    print("See README.md -> 'Choosing your AI provider' for all options.")


def main():
    if not config.PROVIDER_SPECS:
        _no_providers_message()
        sys.exit(1)

    if len(sys.argv) > 1 and sys.argv[1] == "--providers":
        agent = KomenAgent(verbose=False)
        print("Configured providers, in fallback order:")
        for i, label in enumerate(agent.chain.describe(), 1):
            print(f"  {i}. {label}")
        return

    agent = KomenAgent()

    if len(sys.argv) > 1:
        goal = " ".join(sys.argv[1:])
        result = agent.run_task(goal)
        print("\n=== FINAL RESULT ===")
        print(result)
        return

    print("Komen AI is ready. Describe a task, or type 'exit' to quit.")
    while True:
        goal = input("\nYou: ").strip()
        if goal.lower() in ("exit", "quit"):
            break
        if not goal:
            continue
        result = agent.run_task(goal)
        print("\n=== FINAL RESULT ===")
        print(result)


if __name__ == "__main__":
    main()
