from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('core.urls')),
]

# Los archivos subidos (productos/, tienda/) se sirven desde MEDIA_ROOT tanto
# en local como en producción: las imágenes se suben directamente a esa carpeta
# en el servidor y Django las entrega por /media/. En producción los estáticos
# los sirve WhiteNoise, no este bloque.
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0])
