#!/usr/bin/env python3
"""Generate fake users for testing."""

import random
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from cadence import create_app
from cadence.models import User

FIRST_NAMES = [
    "Alice", "Bob", "Charlie", "Diana", "Eve", "Frank", "Grace", "Henry",
    "Ivy", "Jack", "Kate", "Leo", "Mia", "Noah", "Olivia", "Paul", "Quinn",
    "Ruby", "Sam", "Tara", "Uma", "Victor", "Wendy", "Xander", "Yara", "Zoe",
    "Adam", "Bella", "Carl", "Dora", "Ethan", "Fiona", "George", "Hannah",
    "Ian", "Julia", "Kevin", "Luna", "Marcus", "Nina", "Oscar", "Petra",
    "Raj", "Sara", "Tom", "Ursula", "Vera", "Walter", "Xena", "Yuri"
]

LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
    "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark",
    "Ramirez", "Lewis", "Robinson", "Walker", "Young", "Allen", "King",
    "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores", "Green",
    "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell", "Mitchell"
]

DOMAINS = ["example.com", "test.org", "demo.net", "sample.io", "fake.dev"]


def generate_users(count: int = 100) -> None:
    """Generate fake users."""
    app = create_app()

    with app.app_context():
        existing = User.count()
        print(f"Existing users: {existing}")

        created = 0
        for i in range(count):
            first = random.choice(FIRST_NAMES)
            last = random.choice(LAST_NAMES)
            domain = random.choice(DOMAINS)

            # Create unique email
            email = f"{first.lower()}.{last.lower()}{i}@{domain}"
            display_name = f"{first} {last}"

            # Check if exists
            if User.get_by_email(email):
                continue

            User.create(email=email, display_name=display_name)
            created += 1

            if created % 10 == 0:
                print(f"Created {created} users...")

        print(f"Done! Created {created} new users.")
        print(f"Total users: {User.count()}")


if __name__ == "__main__":
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    generate_users(count)
