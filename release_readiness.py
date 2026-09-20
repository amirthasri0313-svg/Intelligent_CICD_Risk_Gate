def calculate_readiness(
    change_score,
    tests_passed,
    security_passed,
    quality_passed
):

    score = 100

    # Change impact
    score -= change_score * 0.4

    # Test result
    if not tests_passed:
        score -= 30

    # Security result
    if not security_passed:
        score -= 20

    # Code quality result
    if not quality_passed:
        score -= 10

    return max(0, round(score))


def get_release_decision(readiness_score):

    if readiness_score >= 75:
        return "LOW RISK - AUTO DEPLOY"

    elif readiness_score >= 50:
        return "MEDIUM RISK - MANUAL APPROVAL"

    else:
        return "HIGH RISK - BLOCK RELEASE"


if __name__ == "__main__":

    # Read actual change score
    with open("change_score.txt", "r") as file:
        change_score = int(file.read().strip())

    # Read security result
    with open("security_result.txt", "r") as file:
        security_result = file.read().strip()

    security_passed = security_result == "PASS"

    # Current CI test status
    tests_passed = True

    # Read actual code quality result
    with open("quality_result.txt", "r") as file:
        quality_result = file.read().strip()

    quality_passed = quality_result == "PASS"

    # Calculate release readiness
    readiness = calculate_readiness(
        change_score,
        tests_passed,
        security_passed,
        quality_passed
    )

    # Get release decision
    decision = get_release_decision(readiness)

    # Display results
    print("Change Score:", change_score, "/100")
    print("Security Check:", security_result)
    print("Code Quality Check:", quality_result)
    print("Release Readiness Score:", readiness, "/100")
    print("Release Decision:", decision)

    # Save readiness score for CI/CD pipeline
    with open("readiness_score.txt", "w") as file:
        file.write(str(readiness))