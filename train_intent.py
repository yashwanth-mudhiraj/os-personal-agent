import random
import joblib
from sklearn.pipeline import Pipeline
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

OPEN = ["open", "launch", "start", "bring up"]
CLOSE = ["close", "quit", "exit", "shut"]
MIN = ["minimize", "hide"]
MAX = ["maximize", "fullscreen"]
FOCUS = ["focus", "switch to", "go to", "activate"]

APPS = [
    "chrome", "firefox", "spotify", "discord",
    "notepad", "visual studio code"
]

CONVO = [
    "how are you",
    "tell me a joke",
    "what time is it",
    "explain this"
]

def make_dataset(n=4000):
    X, y = [], []
    for _ in range(n):
        r = random.random()

        if r < 0.15:
            X.append(random.choice(CONVO))
            y.append("conversation")
            continue

        app = random.choice(APPS)
        is_all = random.random() < 0.2

        group = random.choice(["open","close","min","max","focus"])

        if group == "open":
            verb = random.choice(OPEN)
            if is_all:
                X.append(f"{verb} all")
                y.append("open_all")
            else:
                X.append(f"{verb} {app}")
                y.append("open")

        elif group == "close":
            verb = random.choice(CLOSE)
            if is_all:
                X.append(f"{verb} all")
                y.append("close_all")
            else:
                X.append(f"{verb} {app}")
                y.append("close")

        elif group == "min":
            verb = random.choice(MIN)
            if is_all:
                X.append(f"{verb} all")
                y.append("minimize_all")
            else:
                X.append(f"{verb} {app}")
                y.append("minimize")

        elif group == "max":
            verb = random.choice(MAX)
            if is_all:
                X.append(f"{verb} all")
                y.append("maximize_all")
            else:
                X.append(f"{verb} {app}")
                y.append("maximize")

        elif group == "focus":
            verb = random.choice(FOCUS)
            X.append(f"{verb} {app}")
            y.append("focus")

    return X, y

def train():
    X, y = make_dataset()

    clf = Pipeline([
        ("tfidf", TfidfVectorizer(ngram_range=(1,2))),
        ("lr", LogisticRegression(max_iter=2000))
    ])

    clf.fit(X, y)
    joblib.dump(clf, "intent_clf.joblib")
    print("Saved intent_clf.joblib")

if __name__ == "__main__":
    train()
