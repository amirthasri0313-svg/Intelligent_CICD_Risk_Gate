import sys


def risk_gate(readiness_score):

    if readiness_score >= 75:
        return "AUTO DEPLOY"

    elif readiness_score >= 50:
        return "MANUAL APPROVAL REQUIRED"

    else:
        return "RELEASE BLOCKED"


if __name__ == "__main__":

    readiness_score = int(sys.argv[1]) if len(sys.argv) > 1 else 88

    decision = risk_gate(readiness_score)

    print("Readiness Score:", readiness_score)
    print("Risk Gate Decision:", decision)

    # Block deployment for high-risk releases
    if decision == "RELEASE BLOCKED":
        sys.exit(1)