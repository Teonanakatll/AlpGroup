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
from django.contrib.staticfiles.views import serve as serve_static
from django.templatetags.static import static as static_url
from django.urls import include, path, re_path
from django.views.generic import RedirectView
from django.views.static import serve as serve_media

urlpatterns = [
    # Браузер сам запрашивает /favicon.ico там, где в <head> нет иконки (например, в админке)
    path('favicon.ico', RedirectView.as_view(url=static_url('web/img/favicon-32.png'), permanent=False)),
    path('admin/', admin.site.urls),
    path('api/', include('apps.inventory.urls')),
    path('', include('apps.web.urls')),
]

if settings.DEBUG:
    # В разработке Django сам отдаёт фото (статику при DEBUG отдаёт runserver); на сервере это делает Caddy
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
elif settings.SERVE_FILES:
    # Показ через туннель при DEBUG=0: Caddy нет, поэтому и статику, и фото отдаёт Django.
    # Хелпер static() при DEBUG=0 ничего не подключает, поэтому маршруты заданы явно;
    # insecure=True разрешает раздачу статики из папок приложений без collectstatic.
    # lstrip('/'): Django возвращает STATIC_URL как «/static/», а пути в urls пишутся без ведущего слэша.
    static_prefix = settings.STATIC_URL.lstrip('/')
    media_prefix = settings.MEDIA_URL.lstrip('/')
    urlpatterns += [
        re_path(rf'^{static_prefix}(?P<path>.*)$', serve_static, {'insecure': True}),
        re_path(rf'^{media_prefix}(?P<path>.*)$', serve_media, {'document_root': settings.MEDIA_ROOT}),
    ]
