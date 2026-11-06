"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
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
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.templatetags.static import static as static_url
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    # Браузер сам запрашивает /favicon.ico там, где в <head> нет иконки (например, в админке)
    path('favicon.ico', RedirectView.as_view(url=static_url('web/img/favicon-32.png'), permanent=False)),
    path('admin/', admin.site.urls),
    path('api/', include('apps.inventory.urls')),
    path('', include('apps.web.urls')),
]

# В режиме разработки Django сам отдаёт загруженные файлы; на сервере это делает Caddy
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
