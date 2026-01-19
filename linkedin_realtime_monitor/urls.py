"""linkedin_connector URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
import os

from django.conf import settings
from django.http import HttpResponse
from django.urls import path, include
from django.contrib import admin
from django.urls import path

from linkedin_realtime_monitor.settings import IS_PROD_ENV, redis_client, RUNNING_TASKS_KEY


def shutdownz(request):
    result = redis_client.get(RUNNING_TASKS_KEY)
    if not result:
        return HttpResponse('', status=200)
    else:
        return HttpResponse('', status=400)


def healthz(request):
    version_check_file = os.path.join(settings.BASE_DIR, 'version_check.txt')
    if os.path.exists(version_check_file):
        with open(version_check_file, 'r') as f:
            version_content = f.read()
    else:
        version_content = '获取版本信息失败'
    return HttpResponse(version_content, status=200)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('healthz', healthz),
    path('shutdownz', shutdownz),
]
# if not IS_PROD_ENV:
#     urlpatterns.append(path("__debug__/", include("debug_toolbar.urls")))