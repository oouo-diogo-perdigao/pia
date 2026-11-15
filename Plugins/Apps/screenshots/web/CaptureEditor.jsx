import React, { useEffect } from "react";
import { Button, Group, Text } from "@mantine/core";
import { report } from "../../../../src/pia/frontend/api";
// React/Mantine owns the controls. The canvas engine keeps pointer geometry and
// pixel operations imperative, without routing back into the conversation UI.
export default function CaptureEditor() {
  useEffect(() => {
    const style = document.createElement("link");
    style.rel = "stylesheet";
    style.href = "/apps/screenshots/capture.css";
    const loaded = new Promise((resolve, reject) => {
      style.onload = resolve;
      style.onerror = () =>
        reject(Error("Não foi possível carregar o editor de captura."));
    });
    document.head.append(style);
    const engine = "/apps/screenshots/capture.js";
    loaded.then(() => import(/* @vite-ignore */ engine)).catch(report);
    return () => style.remove();
  }, []);
  return (
    <>
      <aside id="toolbar">
        <Group gap="xs">
          <Button id="free" size="xs">
            Mão livre
          </Button>
          <Button id="rectangle" size="xs">
            Retângulo
          </Button>
          <input
            type="color"
            id="ink"
            defaultValue="#ff4278"
            title="Cor da anotação"
          />
          <Text id="ink-size" size="xs">
            3 px
          </Text>
          <Button id="undo" size="xs">
            Desfazer
          </Button>
          <Button id="all" size="xs">
            Tela inteira
          </Button>
          <Button id="cancel" size="xs" variant="subtle">
            Cancelar · Esc
          </Button>
        </Group>
      </aside>
      <div id="capture-sparkles" aria-hidden="true" />
      <div className="capture-mode-badge" aria-hidden="true">
        ✦ Captura PIA · Esc para sair
      </div>
      <div id="stage">
        <canvas id="canvas" />
        <aside id="reminder">
          Esquerdo: selecionar · Ctrl: retângulo
          <br />
          Direito: anotar · roda: espessura
          <br />
          Enter / Espaço: tela inteira · Esc: cancelar
        </aside>
      </div>
      <div hidden>
        <input id="title" />
        <input id="comment" />
        <select id="format" defaultValue="png">
          <option value="png">PNG</option>
          <option value="jpg">JPEG</option>
          <option value="bmp">BMP</option>
        </select>
        <input type="checkbox" id="border" />
      </div>
      <footer>
        <div id="readout" />
        <span id="notice">Carregando captura…</span>
        <label>
          <input type="checkbox" id="bgr" />
          Copiar cor em BBGGRR
        </label>
        <button id="copy-color">Copiar cor</button>
        <label>
          <input type="checkbox" id="smooth" defaultChecked />
          Suavização
        </label>
      </footer>
    </>
  );
}
