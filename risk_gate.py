import sys


def risk_gate(readiness_score):

    if readiness_score >= 75:
        return "AUTO DEPLOY"

    elif readiness_score >= 50:
        return "MANUAL APPROVAL REQUIRED"

    else:
        return "RELEASE BLOCKED"


if __name__ == "__main__":

    if len(sys.argv) > 1:
        readiness_score = int(sys.argv[1])
    else:
        try:
            with open("readiness_score.txt", "r") as file:
                readiness_score = int(file.read().strip())
        except FileNotFoundError:
            print("Error: readiness_score.txt not found.")
            sys.exit(1)

    decision = risk_gate(readiness_score)

    print("Readiness Score:", readiness_score)
    print("Risk Gate Decision:", decision)

    if decision == "RELEASE BLOCKED":
        sys.exit(1)

    elif decision == "MANUAL APPROVAL REQUIRED":
        print("Manual approval required.")
        sys.exit(2)