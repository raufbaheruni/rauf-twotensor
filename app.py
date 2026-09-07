import cv2
import numpy as np
import os
import io
import tempfile
from datetime import datetime
from PIL import Image
from flask import Flask, render_template, request, send_file

try:
    import piexif
except ImportError:
    os.system("pip install piexif")
    import piexif

app = Flask(__name__)

def twotensor_bypass(file_bytes):
    pil_img = Image.open(io.BytesIO(file_bytes))
    if pil_img.mode in ("RGBA", "P"):
        pil_img = pil_img.convert("RGB")
    img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

    # Quality Save: फोटो को 1200px तक सीमित करें (HD रखें)
    max_size = 1200
    h, w = img.shape[:2]
    if max(h, w) > max_size:
        scale = max_size / max(h, w)
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

    # 1. Sub-Pixel Grid Break (बिना क्वालिटी खराब किए AI ग्रिड तोड़ें)
    img_sub = cv2.resize(img, (w-2, h-1), interpolation=cv2.INTER_AREA)
    img_back = cv2.resize(img_sub, (w, h), interpolation=cv2.INTER_LANCZOS4)

    # 2. YCrCb Color Space Split
    ycrcb = cv2.cvtColor(img_back, cv2.COLOR_BGR2YCrCb)
    y, cr, cb = cv2.split(ycrcb)

    # 3. Chroma Subsampling Attack (SynthID तोड़ने के लिए)
    cr_blur = cv2.GaussianBlur(cr, (5, 5), 0)
    cb_blur = cv2.GaussianBlur(cb, (5, 5), 0)

    # 4. 8x8 DCT Block Noise (AI के मैथ्स को फेल करने के लिए)
    noise_cr_small = np.random.normal(0, 3.0, (h//8+1, w//8+1))
    noise_cb_small = np.random.normal(0, 3.0, (h//8+1, w//8+1))
    noise_cr = cv2.resize(noise_cr_small, (w, h), interpolation=cv2.INTER_NEAREST)
    noise_cb = cv2.resize(noise_cb_small, (w, h), interpolation=cv2.INTER_NEAREST)

    cr_att = np.clip(cr_blur.astype(np.float32) + noise_cr, 0, 255).astype(np.uint8)
    cb_att = np.clip(cb_blur.astype(np.float32) + noise_cb, 0, 255).astype(np.uint8)

    # 5. Luminance Sensor Noise (असली कैमरा इफेक्ट)
    y_poisson = np.random.poisson(y * 0.02) * 3
    y_gauss = np.random.normal(0, 1.5, y.shape)
    y_att = np.clip(y.astype(np.float32) + y_poisson + y_gauss, 0, 255).astype(np.uint8)

    ycrcb_att = cv2.merge((y_att, cr_att, cb_att))
    img_color_attack = cv2.cvtColor(ycrcb_att, cv2.COLOR_YCrCb2BGR)

    # 6. Mild JPEG Ghost (AI Latent Space तोड़ने के लिए, HD रखने के लिए 70%)
    _, enc_img = cv2.imencode('.jpg', img_color_attack, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
    img_ghost = cv2.imdecode(enc_img, 1)

    # 7. Unsharp Mask (HD क्वालिटी वापस लाना)
    gaussian = cv2.GaussianBlur(img_ghost, (0, 0), sigmaX=0.6)
    img_sharp = cv2.addWeighted(img_ghost.astype(np.float32), 1.2, gaussian.astype(np.float32), -0.2, 0)
    final_img = np.clip(img_sharp, 0, 255).astype(np.uint8)

    # 8. EXIF Metadata Spoofing
    now = datetime.now().strftime("%Y:%m:%d %H:%M:%S")
    exif_dict = {
        "0th": {
            piexif.ImageIFD.Make: b"Apple",
            piexif.ImageIFD.Model: b"iPhone 16 Pro",
            piexif.ImageIFD.Software: b"17.4.1",
            piexif.ImageIFD.DateTime: now.encode('utf-8'),
            piexif.ImageIFD.XResolution: (72, 1),
            piexif.ImageIFD.YResolution: (72, 1),
            piexif.ImageIFD.ResolutionUnit: 2
        },
        "Exif": {
            piexif.ExifIFD.DateTimeOriginal: now.encode('utf-8'),
            piexif.ExifIFD.DateTimeDigitized: now.encode('utf-8'),
            piexif.ExifIFD.LensModel: b"iPhone 16 Pro back triple camera 24mm f/1.78",
            piexif.ExifIFD.LensMake: b"Apple",
            piexif.ExifIFD.ExposureTime: (1, 120),
            piexif.ExifIFD.FNumber: (18, 10),
            piexif.ExifIFD.ISOSpeedRatings: 64,
            piexif.ExifIFD.PixelXDimension: w,
            piexif.ExifIFD.PixelYDimension: h
        }
    }
    exif_bytes = piexif.dump(exif_dict)

    img_rgb = cv2.cvtColor(final_img, cv2.COLOR_BGR2RGB)
    pil_final_img = Image.fromarray(img_rgb)

    temp_dir = tempfile.gettempdir()
    out_path = os.path.join(temp_dir, "BAHERUNI.jpg")
    pil_final_img.save(out_path, "JPEG", quality=98, subsampling=2, exif=exif_bytes)
    
    return out_path

@app.route('/profile.jpg')
def profile_pic():
    return send_file('profile.jpg', mimetype='image/jpeg')

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload():
    if 'file' not in request.files:
        return "No file uploaded", 400
    file = request.files['file']
    if file.filename == '':
        return "No file selected", 400
    
    try:
        file_bytes = file.read()
        output_path = twotensor_bypass(file_bytes)
        return send_file(output_path, as_attachment=True, download_name='BAHERUNI.jpg')
    except Exception as e:
        import traceback
        return traceback.format_exc(), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
