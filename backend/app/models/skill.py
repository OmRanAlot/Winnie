# Skill — tags used to suggest substitutes (e.g. Secretary covering a PR task).
# Many-to-many with Member, and with Task (required skills).


from dataclasses import dataclass


@dataclass
class Skill:
    id: int
    name: str  # e.g., "PR", "Finance", "Event Planning"

    def __post_init__(self):
        if not self.name:
            raise ValueError("Skill name cannot be empty.")


