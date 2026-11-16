from django.core.management.base import BaseCommand

from businesses.models import Permission
from businesses.permission_catalogue import PERMISSION_CATALOGUE


class Command(BaseCommand):
    help = "Populate the system permission catalogue."

    def handle(self, *args, **options):
        created_count = 0
        updated_count = 0

        for item in PERMISSION_CATALOGUE:
            permission, created = Permission.objects.update_or_create(
                code=item["code"],
                defaults={
                    "name": item["name"],
                    "description": item["description"],
                    "category": item["category"],
                },
            )

            if created:
                created_count += 1
            else:
                updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Permission catalogue populated. "
                f"Created: {created_count}, "
                f"updated: {updated_count}."
            )
        )