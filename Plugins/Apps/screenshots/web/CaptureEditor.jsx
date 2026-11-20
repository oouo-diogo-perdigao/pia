import React, { useEffect } from "react";
import { Button, Group, Text } from "@mantine/core";
import { report } from "../../../../src/pia/frontend/api";
// React/Mantine owns the controls. The canvas engine keeps pointer geometry and
// pixel operations imperative, without routing back into the conversation UI.
export default function CaptureEditor() {
  useEffect(() => {
    let addedStyle = null;
    if (!document.querySelector('link[href="/apps/screenshots/capture.css"]')) {
      const style = document.createElement("link");
      style.rel = "stylesheet";
      style.href = "/apps/screenshots/capture.css";
      document.head.append(style);
      addedStyle = style;
    }
    const engine = "/apps/screenshots/capture.js";
    import(/* @vite-ignore */ engine).catch(report);
    return () => {
      if (addedStyle) addedStyle.remove();
    };
  }, []);
  return (
    <>
      <aside
        id="toolbar"
        role="toolbar"
        aria-label="Ferramentas da captura"
      >
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
            aria-label="Cor da anotação"
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
      <div className="capture-vignette" aria-hidden="true" />
      <div className="capture-frame" aria-hidden="true" />
      <div id="capture-sparkles" aria-hidden="true" />
      <div className="capture-mode-badge" aria-hidden="true">
        ❄ Captura congelada · Arraste para recortar · Esc para cancelar
      </div>
      <div id="stage">
        <canvas
          id="canvas"
          tabIndex={-1}
          aria-label="Captura congelada da tela. Use o mouse para recortar ou anotar."
        />
        <aside id="reminder">
          Esquerdo: selecionar · Ctrl: retângulo
          <br />
          Direito: anotar · roda: espessura
          <br />
          Enter / Espaço: tela inteira · Esc: cancelar
        </aside>
      </div>
      <div id="capture-error" hidden>
        <div className="capture-error-card" role="alert">
          <p id="capture-error-text">
            Não foi possível abrir a captura. Feche e tente de novo.
          </p>
          <Button id="capture-error-close" size="xs">
            Fechar · Esc
          </Button>
        </div>
      </div>
      <div
        id="capture-status"
        role="status"
        aria-live="polite"
        className="sr-only"
      />
      <div id="capture-alert" role="alert" className="sr-only" />
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
        <span id="notice" hidden>
          Carregando captura…
        </span>
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
