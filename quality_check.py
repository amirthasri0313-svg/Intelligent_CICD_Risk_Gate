import shutil
import subprocess
import sys


def main():
    print("Running Ruff Code Quality Scan...")

    ruff = shutil.which("ruff")

    if ruff is None:
        print("Ruff executable not found.")
        with open("quality_result.txt", "w") as file:
            file.write("FAIL\n")
        return 1

    result = subprocess.run(
        [ruff, "check", "."],
        check=False
    )

    if result.returncode == 0:
        print("\nCode Quality Check: PASSED")

        with open("quality_result.txt", "w") as file:
            file.write("PASS\n")

        return 0

    print("\nCode Quality Check: FAILED")

    with open("quality_result.txt", "w") as file:
        file.write("FAIL\n")

    return 1


if __name__ == "__main__":
    sys.exit(main())