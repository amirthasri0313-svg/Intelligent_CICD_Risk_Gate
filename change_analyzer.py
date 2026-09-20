import subprocess


def get_changed_files():
    result = subprocess.run(
        ["git", "diff", "--name-only", "HEAD~1", "HEAD"],
        capture_output=True,
        text=True
    )

    return [
        file.strip()
        for file in result.stdout.splitlines()
        if file.strip()
    ]


def calculate_change_score(files):
    score = 0

    for file in files:

        # Application source code
        if file.endswith(".py"):
            score += 20

        # CI/CD configuration
        elif ".github/workflows" in file:
            score += 30

        # Dependency changes
        elif file in ["requirements.txt", "package.json"]:
            score += 25

        # Test changes
        elif "test" in file.lower():
            score += 10

        # Other files
        else:
            score += 5

    return min(score, 100)


if __name__ == "__main__":
    changed_files = get_changed_files()
    change_score = calculate_change_score(changed_files)

    print("Changed Files:")
    for file in changed_files:
        print(f" - {file}")

    print(f"\nChange Score: {change_score}/100")