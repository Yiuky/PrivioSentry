# SPDX-License-Identifier: AGPL-3.0-or-later
import os
from PIL import Image, ImageDraw, ImageFont

class SpatialGrid:
    def __init__(self, cols=5, rows=8):
        self.cols = cols
        self.rows = rows
        self.cells = {} # Mapa A1 -> {"x": 0, "y": 0, "w": 100, "h": 100}

    def _get_label(self, c, r):
        # Gera labels: A1, B2, etc. (c=0 -> A)
        letter = chr(65 + c)
        number = r + 1
        return f"{letter}{number}"

    def build_grid(self, img_width, img_height):
        cell_w = img_width / self.cols
        cell_h = img_height / self.rows
        
        for r in range(self.rows):
            for c in range(self.cols):
                label = self._get_label(c, r)
                self.cells[label] = {
                    "x": int(c * cell_w),
                    "y": int(r * cell_h),
                    "w": int(cell_w),
                    "h": int(cell_h)
                }

    def render_grid_on_image(self, img_path, output_path):
        try:
            with Image.open(img_path) as img:
                img = img.convert("RGBA")
                self.build_grid(img.width, img.height)
                
                # Cria overlay transparente
                overlay = Image.new('RGBA', img.size, (255, 255, 255, 0))
                draw = ImageDraw.Draw(overlay)
                
                # Tenta carregar uma fonte default ou nativa do sistema
                font_size = max(20, int(img.height * 0.02))
                try:
                    font = ImageFont.truetype("arial.ttf", font_size)
                except IOError:
                    font = ImageFont.load_default()

                # Desenha Retângulos e Texto
                for label, box in self.cells.items():
                    bx1 = box["x"]
                    by1 = box["y"]
                    bx2 = bx1 + box["w"]
                    by2 = by1 + box["h"]
                    
                    # Linha da grade (vermelhas com baixa opacidade)
                    draw.rectangle([bx1, by1, bx2, by2], outline=(255, 0, 0, 80), width=3)
                    
                    # Fundo de texto pra leitura forte
                    draw.rectangle([bx1 + 10, by1 + 10, bx1 + 10 + font_size*2, by1 + 10 + font_size*1.2], fill=(0, 0, 0, 180))
                    # draw.text (sintaxe básica para garantir compatibilidade Pillow)
                    draw.text((bx1 + 15, by1 + 10), label, font=font, fill=(255, 255, 255, 255))
                
                final_img = Image.alpha_composite(img, overlay).convert("RGB")
                final_img.save(output_path, "JPEG", quality=85)
                return output_path
        except Exception as e:
            print(f"Erro no desenho do Grid: {e}")
            return img_path

    def get_coords(self, cell_id):
        return self.cells.get(cell_id.upper())
