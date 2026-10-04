# SPDX-License-Identifier: AGPL-3.0-or-later
import os
import sys

# Garante que as importações absolutas de agent_loop funcionem (quando rodando desta pasta)
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_loop.core_agent import ReActAgent
from PIL import Image

def init_environment():
    # Carrega as configurações do .env automaticamente para o pipeline
    from dotenv import load_dotenv
    load_dotenv()

if __name__ == "__main__":
    init_environment()
    
    # Importação dinâmica do App Principal
    from main import SentryApp
    
    pdf_path = input("\n[?] Digite o caminho absoluto do arquivo .pdf: ").strip()
    pdf_path = pdf_path.strip('\"\'')
    
    if not os.path.isfile(pdf_path) or not pdf_path.lower().endswith(".pdf"):
        print("Erro: Caminho de PDF inválido.")
        sys.exit(1)
        
    # --- PARTE 1: HEURÍSTICA MASTER + IA SEMÂNTICA ---
    print("\n[*] --- INICIANDO MOTOR DE HEURÍSTICA MASTER (Tesseract + IA de Endereços) ---")
    app = SentryApp(pdf_path)
    # Rodamos as fases de descoberta inicial, IA de endereços e YOLO
    app.logger.info("Executando Setup, OCR, IA de Endereços e YOLO...")
    app.run_phase_0() # Render
    app.run_phase_1() # OCR
    app.run_phase_2() # CPF Discovery
    app.run_phase_3() # YOLO Discovery
    app.run_phase_4() # Micro-Audit (Crops)
    app.run_address_discovery() # IA de Endereços
    app.run_phase_6() # Tarjamento de Endereços
    
    # Extraímos o contexto da Página 1
    page_1_img = app.image_paths[0]
    page_1_boxes = app.global_redactions.get(1, [])
    page_1_pii = getattr(app, 'known_cpfs', [])
    
    # Busca endereços detectados para a memória do agente (Ajustado para chave 'text')
    addresses_found = []
    if hasattr(app.address_redactor, 'results'):
        for addr_obj in app.address_redactor.results.get(1, []):
            extracted = addr_obj.get("text", "")
            if extracted: addresses_found.append(extracted)

    # Captura Regiões do YOLO (Assinaturas/Carimbos)
    yolo_regions = []
    if hasattr(app, 'all_crops_metadata'):
        for crop in app.all_crops_metadata:
            if crop["page_num"] == 1:
                yolo_regions.append(crop["origin_bbox"]) # [x, y, w, h]

    discovery_context = {
        "pii_list": [str(c) for c in page_1_pii],
        "address_list": addresses_found,
        "boxes": page_1_boxes,
        "yolo_regions": yolo_regions
    }
    print(f"[*] Heurística concluída. {len(page_1_boxes)} tarjas automáticas enviadas ao Agente.")
    print(f"[*] CPFs detectados pela Máquina: {discovery_context['pii_list']}")
    print(f"[*] Regiões Suspeitas (YOLO): {len(yolo_regions)} áreas identificadas.")
    print(f"[*] Endereços detectados pela Máquina: {discovery_context['address_list']}")

    # --- PARTE 2: AGENTE AUTÔNOMO ---
    print("\n[*] --- INICIANDO AGENTE NEURAL (Ouvidoria de Elite) ---")
    try:
        agent = ReActAgent(page_1_img)
        # O Agente começa o loop já recebendo as tarjas que a heurística fez
        agent.run_loop(max_steps=50, discovery_context=discovery_context)
        
        # --- RELATÓRIO FINAL CONSOLIDADO ---
        import json
        report = {
            "source_pdf": pdf_path,
            "heuristic_findings": {
                "cpfs": discovery_context["pii_list"],
                "addresses": discovery_context["address_list"]
            },
            "agent_audit_log": agent.log_file,
            "final_image": agent.output_img
        }
        
        report_path = os.path.join(os.path.dirname(page_1_img), "agent_redaction_report.json")
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=4, ensure_ascii=False)
            
        print(f"\n[OK] Relatório consolidado salvo em: {report_path}")

    except KeyboardInterrupt:
        print("\nCancelado manualmente.")

