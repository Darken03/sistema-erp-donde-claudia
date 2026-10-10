import io
import os
from django import forms
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.forms import inlineformset_factory
from PIL import Image
from .models import Producto, Categoria, Empleado, PresentacionProducto, PerfilUsuario

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except Exception:
    pass


def _es_heic(nombre, content_type=None):
    ext = os.path.splitext(nombre or '')[1].lower()
    if ext in ('.heic', '.heif'):
        return True
    ct = (content_type or '').lower()
    return ct in ('image/heic', 'image/heif', 'image/heic-sequence', 'image/heif-sequence')


def _convertir_a_jpeg(uploaded_file):
    """Convierte un archivo subido (HEIC/HEIF) a JPEG en memoria."""
    uploaded_file.seek(0)
    img = Image.open(uploaded_file)
    if getattr(img, 'format', None) in ('HEIF', 'HEIC'):
        pass
    if img.mode in ('RGBA', 'LA', 'PA'):
        fondo = Image.new('RGB', img.size, (255, 255, 255))
        fondo.paste(img, mask=img.split()[-1])
        img = fondo
    else:
        img = img.convert('RGB')
    # Limita a 1920px para no guardar fotos gigantes de celular
    img.thumbnail((1920, 1920), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=90, optimize=True)
    buf.seek(0)
    base = os.path.splitext(getattr(uploaded_file, 'name', 'foto') or 'foto')[0]
    return SimpleUploadedFile(f'{base}.jpg', buf.read(), content_type='image/jpeg')


class ProductoForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Convierte ANTES de que ImageField valide: si no, el .heic
        # falla con "Suba una imagen valida" y clean_imagen ni se ejecuta.
        try:
            f = self.files.get('imagen') if hasattr(self, 'files') and self.files else None
        except Exception:
            f = None
        if f and _es_heic(getattr(f, 'name', ''), getattr(f, 'content_type', '')):
            try:
                convertido = _convertir_a_jpeg(f)
                if hasattr(self.files, 'setlist'):
                    self.files.setlist('imagen', [convertido])
                else:
                    self.files['imagen'] = convertido
            except Exception:
                pass

    def clean_imagen(self):
        f = self.cleaned_data.get('imagen')
        if not f:
            return f
        if _es_heic(getattr(f, 'name', ''), getattr(f, 'content_type', '')):
            try:
                return _convertir_a_jpeg(f)
            except Exception:
                raise forms.ValidationError(
                    'No se pudo leer la imagen HEIC. Cambie el iPhone a '
                    'Ajustes > Camara > Formatos > Mas compatible o use JPG.'
                )
        return f

    class Meta:
        model = Producto
        fields = [
            'nombre', 'descripcion', 'categoria', 'unidad_medida',
            'precio_compra', 'precio_venta', 'stock', 'stock_minimo',
            'permite_decimal', 'imagen', 'activo'
        ]
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nombre del producto'}),
            'descripcion': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'categoria': forms.Select(attrs={'class': 'form-select'}),
            'unidad_medida': forms.Select(attrs={'class': 'form-select'}),
            'precio_compra': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'precio_venta': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'stock': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.001'}),
            'stock_minimo': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.001'}),
            'permite_decimal': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'imagen': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'activo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        help_texts = {
            'permite_decimal': 'Actívelo para vender fracciones con 3 decimales (ej. 2.500 lb, 0.5 cartón).',
            'stock': 'Stock en UNIDAD BASE (lb para cerdo, und para huevo). Admite 3 decimales.',
        }


class PresentacionProductoForm(forms.ModelForm):
    class Meta:
        model = PresentacionProducto
        fields = ['nombre', 'factor', 'precio', 'es_default', 'activo']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej. Libra, Media libra, Unidad, Docena, Cartón 30, Medio cartón'}),
            'factor': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.001', 'min': '0.001'}),
            'precio': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'es_default': forms.CheckboxInput(attrs={'class': 'form-check-input pres-default'}),
            'activo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        help_texts = {
            'factor': 'Unidades base por 1 de esta presentación (Libra=1, Media libra=0.5, Docena=12, Cartón 30=30, Medio cartón=15).',
            'precio': 'Precio MANUAL de esta presentación.',
        }

    def clean_factor(self):
        f = self.cleaned_data.get('factor')
        if f is not None and f <= 0:
            raise forms.ValidationError('El factor debe ser mayor a 0.')
        return f


PresentacionFormSet = inlineformset_factory(
    Producto, PresentacionProducto,
    form=PresentacionProductoForm,
    extra=1, can_delete=True,
)


class CategoriaForm(forms.ModelForm):
    class Meta:
        model = Categoria
        fields = ['nombre', 'descripcion']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nombre de la categoria'}),
            'descripcion': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


class EmpleadoForm(forms.ModelForm):
    username = forms.CharField(
        max_length=150,
        label='Usuario',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nombre de usuario', 'autocomplete': 'username'})
    )
    password = forms.CharField(
        max_length=128,
        label='Contrasena',
        required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Contrasena', 'autocomplete': 'new-password'})
    )
    first_name = forms.CharField(
        max_length=150,
        label='Nombre',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nombre'})
    )
    last_name = forms.CharField(
        max_length=150,
        label='Apellido',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Apellido'})
    )
    rol = forms.ChoiceField(
        label='Rol',
        choices=PerfilUsuario.ROLES,
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text='Almacenero: solo gestiona el almacén (sin POS ni turnos).',
    )

    class Meta:
        model = Empleado
        fields = ['salario', 'activo']
        widgets = {
            'salario': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'activo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        self.user_instance = kwargs.pop('user_instance', None)
        super().__init__(*args, **kwargs)
        if self.user_instance:
            self.fields['username'].initial = self.user_instance.username
            self.fields['first_name'].initial = self.user_instance.first_name
            self.fields['last_name'].initial = self.user_instance.last_name
            self.fields['password'].required = False
            self.fields['password'].help_text = 'Dejar vacio para no cambiar la contrasena'
            try:
                self.fields['rol'].initial = self.user_instance.perfil.rol
            except PerfilUsuario.DoesNotExist:
                pass
        else:
            self.fields['password'].required = True

    def clean_username(self):
        username = self.cleaned_data['username']
        qs = User.objects.filter(username=username)
        if self.user_instance:
            qs = qs.exclude(pk=self.user_instance.pk)
        if qs.exists():
            raise forms.ValidationError('Este nombre de usuario ya esta en uso.')
        return username

    def save(self, commit=True):
        empleado = super().save(commit=False)
        if self.user_instance:
            user = self.user_instance
        else:
            user = User()
        user.username = self.cleaned_data['username']
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        password = self.cleaned_data.get('password')
        if password:
            user.set_password(password)
        if commit:
            user.save()
            empleado.user = user
            empleado.save()
            perfil, _ = PerfilUsuario.objects.get_or_create(user=user)
            perfil.rol = self.cleaned_data.get('rol', 'cajero')
            perfil.save()
        return empleado
