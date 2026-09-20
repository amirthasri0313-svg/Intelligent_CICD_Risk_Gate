import subprocess


def run_quality_check():
    print("Running Ruff Code Quality Scan...")

    result = subprocess.run(
        ["ruff", "check", "."],
        capture_output=True,
        text=True,
        check=False
    )

    if result.stdout:
        print(result.stdout)

    if result.returncode == 0:
        print("Code Quality Check: PASSED")
        status = "PASS"
    else:
        print("Code Quality Check: FAILED")
        status = "FAIL"

    with open("quality_result.txt", "w") as file:
        file.write(status)

    return result.returncode == 0


if __name__ == "__main__":
    run_quality_check()