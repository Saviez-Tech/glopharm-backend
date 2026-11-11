
from rest_framework.response import Response


class APIResponse:

    @staticmethod
    def success(message="Success", data=None, status_code=200):
        return Response({
            "status_code": status_code,
            "message": message,
            "data": data
        }, status=status_code)

    @staticmethod
    def error(message="An error occurred", data=None, status_code=400):
        return Response({
            "status_code": status_code,
            "message": str(message),
            "data": data
        }, status=status_code)

    @staticmethod
    def validation_error(errors, status_code=400):
        message = "Invalid request."

        if isinstance(errors, dict):
            for field_errors in errors.values():
                if isinstance(field_errors, list) and field_errors:
                    message = str(field_errors[0])
                    break

        elif isinstance(errors, list) and errors:
            message = str(errors[0])

        return Response({
            "status_code": status_code,
            "message": message,
            "data": None
        }, status=status_code)



from rest_framework.views import exception_handler as drf_exception_handler


def custom_exception_handler(exc, context):
    response = drf_exception_handler(exc, context)

    if response is None:
        return None

    errors = response.data

    def get_first_error(value):
        if isinstance(value, dict):
            for item in value.values():
                result = get_first_error(item)
                if result:
                    return result

        elif isinstance(value, (list, tuple)):
            for item in value:
                result = get_first_error(item)
                if result:
                    return result

        elif value:
            return str(value)

        return None

    message = get_first_error(errors) or "An error occurred."

    response.data = {
        "status_code": response.status_code,
        "message": message,
        "data": None
    }

    return response

from rest_framework.pagination import PageNumberPagination

class OrderPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = "page_size"
    max_page_size = 50

    def get_paginated_data(self, data):
        return {
            "count": self.page.paginator.count,
            "next": self.get_next_link(),
            "previous": self.get_previous_link(),
            "results": data,
        }