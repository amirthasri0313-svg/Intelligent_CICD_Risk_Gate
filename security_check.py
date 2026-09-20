import subprocess


def run_security_check():
    print("Running Bandit Security Scan...")

    result = subprocess.run(
        ["bandit", "-r", ".", "-x", "./.git,./__pycache__", "--severity-level", "medium"],
        capture_output=True,
        text=True,
        check=False
    )

    print(result.stdout)

    if result.returncode == 0:
        print("Security Check: PASSED")
        status = "PASS"
    else:
        print("Security Check: FAILED")
        status = "FAIL"

    with open("security_result.txt", "w") as file:
        file.write(status)

    return result.returncode == 0


if __name__ == "__main__":
    run_security_check()