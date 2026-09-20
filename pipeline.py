import subprocess
import sys


def run_stage(name, command):
    print("\n" + "=" * 60)
    print(f"RUNNING: {name}")
    print("=" * 60)

    result = subprocess.run(command, check=False)

    if result.returncode != 0:
        print(f"\n{name}: FAILED")
        return False

    print(f"\n{name}: PASSED")
    return True


def main():
    print("\n" + "=" * 60)
    print("   INTELLIGENT CI/CD RISK GATE PIPELINE")
    print("=" * 60)

    stages = [
        ("CHANGE ANALYZER", [sys.executable, "change_analyzer.py"]),
        ("QUALITY CHECK", [sys.executable, "quality_check.py"]),
        ("SECURITY CHECK", [sys.executable, "security_check.py"]),
    ]

    for name, command in stages:
        if not run_stage(name, command):
            print("\n" + "=" * 60)
            print("CI/CD PIPELINE: BLOCKED")
            print("=" * 60)
            sys.exit(1)

    print("\n" + "=" * 60)
    print("RUNNING: RISK GATE")
    print("=" * 60)

    result = subprocess.run(
        [sys.executable, "risk_gate.py"],
        check=False
    )

    if result.returncode != 0:
        print("\nCI/CD PIPELINE: BLOCKED")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("CI/CD PIPELINE COMPLETED")
    print("=" * 60)


if __name__ == "__main__":
    main()