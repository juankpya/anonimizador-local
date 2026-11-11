#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Pruebas de extremo a extremo de los hooks, con los documentos de ejemplo.

    python pruebas/test_plugin.py

Cada hook se lanza como lo lanza Claude Code: un proceso que recibe JSON por
la entrada estandar. Usa una carpeta temporal como ~/.anonimizador, asi que no
toca tus datos. Las pruebas de lectura necesitan el entorno instalado
(python instalar.py); si no lo esta, se saltan.

Todos los datos de ejemplos/ son ficticios.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from anonimizador import config  # noqa: E402

ENTORNO = config.python_del_entorno()
REALES = ["Maria Fernandez Lopez", "12345678Z", "maria.fernandez@example.com",
          "ES9121000418450200051332", "Pedro Ruiz Gomez"]


class Base(unittest.TestCase):
    CONFIG: dict = {}

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="anonimizador-pruebas-"))
        cls.home = cls.tmp / "home"
        cls.proyecto = cls.tmp / "proyecto"
        (cls.proyecto / "originales").mkdir(parents=True)
        for nombre in ("contrato.docx", "contrato.pdf", "clientes.xlsx",
                       "contrato_foto.png", "contrato_escaneado.pdf", "sin_texto.png"):
            shutil.copy(RAIZ / "ejemplos" / nombre, cls.proyecto / nombre)
        for nombre in ("contrato.txt", "ficha.json", "sin_texto.png"):
            shutil.copy(RAIZ / "ejemplos" / nombre, cls.proyecto / "originales" / nombre)
        (cls.proyecto / "notas.md").write_text("# Notas\nNada sensible.\n", encoding="utf-8")
        (cls.proyecto / "foto.png").write_bytes(b"\x89PNG\r\n")
        if cls.CONFIG:
            (cls.proyecto / ".anonimizador.json").write_text(
                json.dumps(cls.CONFIG), encoding="utf-8")
        cls.env = dict(os.environ, ANONIMIZADOR_HOME=str(cls.home),
                       CLAUDE_PROJECT_DIR=str(cls.proyecto), PYTHONUTF8="1")
        if ENTORNO:
            cls.env["ANONIMIZADOR_PYTHON"] = str(ENTORNO)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def hook(self, nombre: str, carga: dict) -> dict:
        carga.setdefault("cwd", str(self.proyecto))
        p = subprocess.run([sys.executable, str(RAIZ / "hooks" / nombre)],
                           input=json.dumps(carga), capture_output=True, text=True,
                           encoding="utf-8", env=self.env, timeout=300)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout) if p.stdout.strip() else {}

    def guardia(self, herramienta: str, **entrada) -> dict:
        salida = self.hook("guardia.py", {"hook_event_name": "PreToolUse",
                                          "tool_name": herramienta, "tool_input": entrada})
        return salida.get("hookSpecificOutput", {})

    def ruta(self, *partes: str) -> str:
        return str(self.proyecto.joinpath(*partes))


class A_Guardia(Base):
    """Decisiones que no necesitan el entorno pesado."""

    CONFIG = {"imagenes": "preguntar"}

    def test_fichero_normal_pasa(self):
        self.assertEqual(self.guardia("Read", file_path=self.ruta("notas.md")), {})

    def test_imagen_pregunta(self):
        self.assertEqual(self.guardia("Read", file_path=self.ruta("foto.png"))
                         .get("permissionDecision"), "ask")

    def test_carpeta_privada_denegada(self):
        mapa = str(self.home / "proyectos" / "x" / "mapa.json")
        self.assertEqual(self.guardia("Read", file_path=mapa).get("permissionDecision"), "deny")

    def test_revelado_denegado(self):
        self.assertEqual(self.guardia("Read", file_path=self.ruta("x.revelado.md"))
                         .get("permissionDecision"), "deny")

    def test_editar_original_denegado(self):
        self.assertEqual(self.guardia("Edit", file_path=self.ruta("originales", "contrato.txt"))
                         .get("permissionDecision"), "deny")

    def test_editar_config_denegado(self):
        self.assertEqual(self.guardia("Write", file_path=self.ruta(".anonimizador.json"))
                         .get("permissionDecision"), "deny")

    def test_escribir_fichero_nuevo_pasa(self):
        self.assertEqual(self.guardia("Write", file_path=self.ruta("resumen.md")), {})

    def test_grep_sobre_protegida_denegado(self):
        self.assertEqual(self.guardia("Grep", pattern="NIF", path=str(self.proyecto))
                         .get("permissionDecision"), "deny")
        self.assertEqual(self.guardia("Grep", pattern="NIF", path=self.ruta("originales"))
                         .get("permissionDecision"), "deny")

    def test_bash_sobre_protegida_denegado(self):
        for orden in ("cat originales/contrato.txt", "type originales\\ficha.json",
                      "ls ~/.anonimizador/proyectos", "cat informe.revelado.md"):
            self.assertEqual(self.guardia("Bash", command=orden).get("permissionDecision"),
                             "deny", orden)

    def test_bash_sobre_documento_pregunta(self):
        self.assertEqual(self.guardia("Bash", command="pandoc contrato.docx -t plain")
                         .get("permissionDecision"), "ask")

    def test_bash_normal_pasa(self):
        for orden in ("git status", "ls -la", "python script.py > informe.pdf"):
            self.assertEqual(self.guardia("Bash", command=orden), {}, orden)

    def test_orden_propia_pasa_solo_sin_encadenar(self):
        self.assertEqual(self.guardia("Bash", command='python "x/anonimizar.py" --revelar a.md'), {})
        self.assertEqual(self.guardia(
            "Bash", command="python anonimizar.py --estado; cat originales/contrato.txt")
            .get("permissionDecision"), "deny")


@unittest.skipUnless(ENTORNO, "entorno no instalado (python instalar.py)")
class B_Lectura(Base):
    """Read -> conversion -> anonimizado -> redireccion; despues prompt y pantalla."""

    def leer(self, *partes: str) -> tuple[dict, str]:
        salida = self.guardia("Read", file_path=self.ruta(*partes), pages="1-2")
        self.assertEqual(salida.get("permissionDecision"), "allow", salida)
        nueva = salida["updatedInput"]
        self.assertNotIn("pages", nueva)
        return salida, Path(nueva["file_path"]).read_text(encoding="utf-8")

    def comprobar_sin_fugas(self, texto: str):
        for real in REALES:
            self.assertNotIn(real, texto)
            self.assertNotIn(real.upper(), texto)

    def test_1_docx(self):
        salida, texto = self.leer("contrato.docx")
        self.assertTrue(salida["updatedInput"]["file_path"].endswith(".md"))
        self.assertIn("PERSONA_", texto)
        self.assertIn("NIF_", texto)
        self.comprobar_sin_fugas(texto)
        self.assertNotIn("contrato", Path(salida["updatedInput"]["file_path"]).name)

    def test_2_pdf_y_xlsx(self):
        for nombre in ("contrato.pdf", "clientes.xlsx"):
            _, texto = self.leer(nombre)
            self.comprobar_sin_fugas(texto)

    def test_3_texto_protegido_conserva_formato(self):
        salida, texto = self.leer("originales", "ficha.json")
        self.assertTrue(salida["updatedInput"]["file_path"].endswith(".json"))
        json.loads(texto)
        self.comprobar_sin_fugas(texto)
        _, texto = self.leer("originales", "contrato.txt")
        self.comprobar_sin_fugas(texto)

    def test_4_mismo_pseudonimo_en_todos_los_documentos(self):
        os.environ["ANONIMIZADOR_HOME"] = str(self.home)
        try:
            from anonimizador.mapa import Mapa
            mapa = Mapa(str(self.proyecto))
        finally:
            os.environ.pop("ANONIMIZADOR_HOME", None)
        personas = [r for p, r in mapa.reales.items() if mapa.tipos[p] == "PERSON"]
        self.assertEqual(len([r for r in personas if "maria fernandez" in r.lower()]), 1)

    def test_5_cache(self):
        a, _ = self.leer("contrato.docx")
        b, _ = self.leer("contrato.docx")
        self.assertEqual(a["updatedInput"]["file_path"], b["updatedInput"]["file_path"])

    def test_6_pantalla_revela(self):
        salida = self.hook("pantalla.py", {
            "hook_event_name": "MessageDisplay",
            "delta": "La arrendataria es **PERSONA_1** (NIF\\_1). PERSONA_999 no existe.\n"})
        texto = salida["hookSpecificOutput"]["displayContent"]
        self.assertIn("Maria Fernandez Lopez", texto)
        self.assertIn("12345678Z", texto)
        self.assertIn("PERSONA_999", texto)
        self.assertEqual(self.hook("pantalla.py", {"delta": "Sin identificadores.\n"}), {})

    def test_7_prompt_bloquea_y_deja_reenviar(self):
        limpio = self.hook("prompt.py", {"prompt": "Resume contrato.docx en tres puntos"})
        self.assertEqual(limpio, {})
        for prompt in ("Mi NIF es 12345678Z",
                       "Escribe a Pedro Ruiz Gomez para avisarle",
                       "Mira esto [Image #1]",
                       "Resume @contrato.docx",
                       "Llama al 612 345 678 o escribe a ana@example.org"):
            primero = self.hook("prompt.py", {"prompt": prompt})
            self.assertEqual(primero.get("decision"), "block", prompt)
            self.assertNotIn("12345678Z", primero["reason"])
            otro = self.hook("prompt.py", {"prompt": prompt + " (editado: IBAN ES9121000418450200051332)"})
            self.assertEqual(otro.get("decision"), "block")
            self.hook("prompt.py", {"prompt": prompt})  # vuelve a quedar pendiente
            self.assertEqual(self.hook("prompt.py", {"prompt": prompt}), {}, prompt)

    def test_8_falsos_positivos_del_prompt(self):
        for prompt in ("El NIF 12345678A no es valido",            # letra incorrecta
                       "Version 4111 1111 1111 1112 del producto",  # no pasa Luhn
                       "Vive en Cordoba"):                          # lugar suelto
            self.assertEqual(self.hook("prompt.py", {"prompt": prompt}), {}, prompt)

    def test_92_ocr_de_imagen(self):
        salida, texto = self.leer("contrato_foto.png")
        self.assertTrue(salida["updatedInput"]["file_path"].endswith(".md"))
        self.assertIn("OCR", salida["additionalContext"])
        self.assertIn("PERSONA_", texto)
        self.assertIn("NIF_", texto)
        self.assertIn("IBAN_", texto)
        self.assertIn("Contrato de arrendamiento", texto)  # el texto normal se conserva
        for real in ("María Fernández López", "12345678Z", "maria.fernandez@example.com",
                     "ES91 2100 0418 4502 0005 1332", "612 345 678", "Pedro Ruiz Gómez"):
            self.assertNotIn(real, texto)

        # Con y sin tildes es la misma persona: mismo identificador que en el .docx.
        _, docx = self.leer("contrato.docx")
        persona = texto.split("Arrendataria: ")[1].split(",")[0]
        self.assertTrue(persona.startswith("PERSONA_"), persona)
        self.assertIn(persona, docx)

    def test_93_ocr_de_pdf_escaneado(self):
        salida, texto = self.leer("contrato_escaneado.pdf")
        self.assertIn("OCR", salida["additionalContext"])
        self.assertIn("## Página 1", texto)
        self.assertIn("PERSONA_", texto)
        self.comprobar_sin_fugas(texto)

    def test_94_imagen_sin_texto(self):
        fuera = self.guardia("Read", file_path=self.ruta("sin_texto.png"))
        self.assertEqual(fuera.get("permissionDecision"), "ask")
        dentro = self.guardia("Read", file_path=self.ruta("originales", "sin_texto.png"))
        self.assertEqual(dentro.get("permissionDecision"), "deny")

    def test_91_preparar_autorizado_y_sin_fugas(self):
        guion = str(RAIZ / "anonimizar.py").replace("\\", "/")
        orden = f'python "{guion}" --proyecto "{self.proyecto}" --preparar "clientes.xlsx"'
        self.assertEqual(self.guardia("Bash", command=orden).get("permissionDecision"), "allow")
        self.assertEqual(self.guardia("PowerShell", command=orden).get("permissionDecision"), "allow")
        self.assertNotEqual(self.guardia("Bash", command=orden + " > x.txt")
                            .get("permissionDecision"), "allow")
        p = subprocess.run([sys.executable, guion, "--proyecto", str(self.proyecto),
                            "--preparar", "clientes.xlsx", "notas.md"], cwd=self.proyecto,
                           env=self.env, capture_output=True, text=True, encoding="utf-8")
        self.assertIn("COPIA ANONIMIZADA:", p.stdout)
        self.assertIn("ERROR", p.stdout)  # notas.md no es un documento protegido
        self.comprobar_sin_fugas(p.stdout)
        copia = p.stdout.split("COPIA ANONIMIZADA: ")[1].split("  (")[0]
        self.assertEqual(self.guardia("Read", file_path=copia), {})  # la cache se puede leer
        self.comprobar_sin_fugas(Path(copia).read_text(encoding="utf-8"))

    def test_9_cli_revelar(self):
        informe = self.proyecto / "informe.md"
        informe.write_text("Titular: PERSONA_1, cuenta IBAN_1.\n", encoding="utf-8")
        p = subprocess.run([sys.executable, str(RAIZ / "anonimizar.py"), "--revelar",
                            "informe.md"], cwd=self.proyecto, env=self.env,
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn("Maria", p.stdout)  # la salida no debe llevar datos reales
        revelado = (self.proyecto / "informe.revelado.md").read_text(encoding="utf-8")
        self.assertIn("Maria Fernandez Lopez", revelado)
        self.assertIn("ES9121000418450200051332", revelado)


class C_Sesion(Base):
    def test_contexto_inicial(self):
        salida = self.hook("sesion.py", {"hook_event_name": "SessionStart"})
        self.assertIn("PERSONA_1", salida["hookSpecificOutput"]["additionalContext"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
