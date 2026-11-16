from rest_framework import serializers

from .models import Permission


class PermissionSerializer(serializers.ModelSerializer):

    class Meta:
        model = Permission
        fields = [
            "id",
            "code",
            "name",
            "description",
            "category",
        ]
        read_only_fields = fields