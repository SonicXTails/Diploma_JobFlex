"""Генератор OpenAPI: добавляет русские описания и примеры к операциям (ReDoc / Swagger)."""

from drf_yasg.generators import OpenAPISchemaGenerator

from .openapi_ru_docs import RU_OPERATION_DESCRIPTIONS, RU_TAG_DESCRIPTIONS


class RussianOpenAPISchemaGenerator(OpenAPISchemaGenerator):
    """Дополняет операции текстом из `openapi_ru_docs` (ключ: путь в схеме + HTTP-метод)."""

    def get_operation(self, view, path, prefix, method, components, request):
        operation = super().get_operation(view, path, prefix, method, components, request)
        if operation is None:
            return None

        suffix = path[len(prefix) :]
        if not suffix.startswith("/"):
            suffix = "/" + suffix

        extra = RU_OPERATION_DESCRIPTIONS.get((suffix, method.lower()))
        if not extra:
            return operation

        current = (operation.get("description") or "").strip()
        operation["description"] = (extra.rstrip() + ("\n\n" + current if current else "")).strip()
        return operation

    def get_schema(self, request=None, public=False):
        schema = super().get_schema(request, public)
        if RU_TAG_DESCRIPTIONS:
            schema["tags"] = RU_TAG_DESCRIPTIONS
        return schema
