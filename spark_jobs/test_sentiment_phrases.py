import argparse
import sys
from pathlib import Path


AIRFLOW_HOME = Path(__file__).resolve().parents[1]
if str(AIRFLOW_HOME) not in sys.path:
    sys.path.insert(0, str(AIRFLOW_HOME))

from spark_jobs.sentiment_analysis import score_review_text


def classify_phrase(phrase):
    features = score_review_text(phrase)
    score = features["sentiment_score"]

    if score > 0:
        label = "positive"
    elif score < 0:
        label = "negative"
    else:
        label = "neutral"

    return label, features


def main():
    parser = argparse.ArgumentParser(description="Test the sentiment classifier on a phrase provided at runtime.")
    parser.add_argument(
        "phrase",
        nargs="+",
        help="Phrase to classify. Wrap it in quotes if it contains spaces.",
    )
    args = parser.parse_args()

    phrase = " ".join(args.phrase).strip()
    if not phrase:
        raise SystemExit("Please provide a phrase to classify.")

    label, features = classify_phrase(phrase)
    print(f"{label.upper()} | score={features['sentiment_score']} | confidence={features['sentiment_confidence']}")
    print(f"positives={features['matched_positive_tokens']} negatives={features['matched_negative_tokens']} segments={features['matched_segment_count']}")
    print(phrase)


if __name__ == "__main__":
    main()