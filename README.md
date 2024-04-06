# clip_studio_paint_tool
CLIP STUDIO PAINT（クリスタ）のファイル（.clip）から、レイヤー名やサムネイル画像、ラスター画像を取得するツールです（非公式）<br>グレースケール画像やモノクロ画像には対応していません<br>
<img src="https://github.com/Kazuhito00/clip_studio_paint_tool/assets/37477845/9a77031b-0f98-4836-ad6f-ae64d7645e57" width="45%">　<img src="https://github.com/Kazuhito00/clip_studio_paint_tool/assets/37477845/21b0d6c5-1b72-4000-8e2c-aad4754e3e19" width="45%">

# Requirement
```
numpy 1.26.2           or later
opencv-python 4.9.0.80 or later
```

# Usage
デモの実行方法は以下です。
```bash
python csp_tool.py
```

```python
# CspToolインスタンス生成
csp_tool = CspTool('test.clip')

# サムネイル画像取得
thumbnail_image = csp_tool.get_thumbnail_image()

# レイヤー情報取得
layer_list = csp_tool.get_layer_list()
for layer_data in layer_list:
    test_string = layer_data['layer_name']
    test_string += ' (Canvas ID:' + str(layer_data['canvas_id'])
    test_string += ' Layer ID:' + str(layer_data['main_id']) + ')'
    print(test_string)

# ラスターデータ取得
bgr_image, alpha_image, bgra_image = csp_tool.get_raster_data(
    canvas_id=1,
    layer_id=3,
)

# 表示確認
cv2.imshow('Clip Studio Paint File : Thumbnail Image', thumbnail_image)
cv2.imshow('Clip Studio Paint File : Image', bgr_image)
cv2.imshow('Clip Studio Paint File : Alpha', alpha_image)
cv2.waitKey(-1)
```

# Author
高橋かずひと(https://twitter.com/KzhtTkhs)
 
# License 
clip_studio_paint_tool is under [MIT License](LICENSE).
