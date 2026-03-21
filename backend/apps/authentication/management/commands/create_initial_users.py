from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.dialer.models import AgentProfile, AgentStatus

User = get_user_model()

INITIAL_USERS = [
    {
        "username": "admin",
        "password": "admin123",
        "is_staff": True,
        "is_superuser": True,
        "first_name": "Admin",
        "last_name": "",
        "display_name": "Admin",
    },
    {
        "username": "agent1",
        "password": "agent123",
        "is_staff": False,
        "is_superuser": False,
        "first_name": "Agent",
        "last_name": "One",
        "display_name": "Agent One",
    },
]


class Command(BaseCommand):
    help = "Create initial admin and agent users with AgentProfiles."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset-passwords",
            action="store_true",
            help="Reset passwords for existing initial users and reactivate them.",
        )

    def handle(self, *args, **options):
        reset_passwords = bool(options.get("reset_passwords"))

        for spec in INITIAL_USERS:
            user, created = User.objects.get_or_create(
                username=spec["username"],
                defaults={
                    "is_staff": spec["is_staff"],
                    "is_superuser": spec["is_superuser"],
                    "first_name": spec["first_name"],
                    "last_name": spec["last_name"],
                },
            )
            if created:
                user.set_password(spec["password"])
                user.save()
                self.stdout.write(
                    self.style.SUCCESS(f"Created user: {spec['username']}")
                )
            else:
                self.stdout.write(f"User already exists: {spec['username']}")
                if reset_passwords:
                    user.set_password(spec["password"])
                    if not user.is_active:
                        user.is_active = True
                        user.save(update_fields=["password", "is_active"])
                    else:
                        user.save(update_fields=["password"])
                    self.stdout.write(
                        self.style.WARNING(
                            f"Reset password for user: {spec['username']}"
                        )
                    )

            profile, p_created = AgentProfile.objects.get_or_create(
                user=user,
                defaults={
                    "display_name": spec["display_name"],
                    "status": AgentStatus.AVAILABLE
                    if not spec["is_superuser"]
                    else AgentStatus.OFFLINE,
                },
            )
            if p_created:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Created AgentProfile for: {spec['username']}"
                    )
                )
            else:
                self.stdout.write(
                    f"AgentProfile already exists for: {spec['username']}"
                )

        self.stdout.write(self.style.SUCCESS("\nInitial users setup complete."))
