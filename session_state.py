class SessionState:
    def __init__(self):
        self.pending_matches = []
        self.last_action_type = None  # "file" | "folder" | None

    def set_pending(self, matches, action_type):
        self.pending_matches = matches
        self.last_action_type = action_type

    def clear(self):
        self.pending_matches = []
        self.last_action_type = None

    def has_pending(self):
        return len(self.pending_matches) > 0

    def show_options(self):
        if not self.has_pending():
            return False

        label = "📄 Files" if self.last_action_type == "file" else "📂 Folders"

        print(f"{label} options:")
        for i, m in enumerate(self.pending_matches):
            print(f"{i+1}. {m.name}")

        print("Say: open number X")
        return True
    
session = SessionState()    # Global session state to manage pending selections and last action type