from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse
import sqlite3
import json
import webbrowser
import threading
import time
import csv
import io
import html

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "curso_informatica.db"
HTML_FILE = "inscricao.html"
HOST = "127.0.0.1"
PORT = 8765

def inicializar_banco():
    """Cria o banco e as turmas padrão na primeira execução."""
    with sqlite3.connect(DB_PATH, timeout=10) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS alunos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome_completo TEXT NOT NULL COLLATE NOCASE,
                rg TEXT UNIQUE,
                cpf TEXT NOT NULL UNIQUE,
                contato TEXT,
                endereco TEXT,
                criado_em TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                atualizado_em TEXT
            );

            CREATE TABLE IF NOT EXISTS turmas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                turno TEXT NOT NULL CHECK (turno IN ('Manhã','Tarde')),
                dias_semana TEXT NOT NULL CHECK (
                    dias_semana IN ('Segunda e Quarta-feira','Terça e Quinta-feira')
                ),
                hora_inicio TEXT NOT NULL,
                hora_fim TEXT NOT NULL,
                capacidade INTEGER NOT NULL DEFAULT 9 CHECK (capacidade > 0),
                ativa INTEGER NOT NULL DEFAULT 1 CHECK (ativa IN (0,1)),
                UNIQUE(turno, dias_semana, hora_inicio, hora_fim)
            );

            CREATE TABLE IF NOT EXISTS matriculas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                aluno_id INTEGER NOT NULL,
                turma_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'ATIVA'
                    CHECK (status IN ('ATIVA','CANCELADA','CONCLUIDA')),
                data_matricula TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                observacao TEXT,
                FOREIGN KEY (aluno_id) REFERENCES alunos(id) ON DELETE RESTRICT,
                FOREIGN KEY (turma_id) REFERENCES turmas(id) ON DELETE RESTRICT
            );

            CREATE TABLE IF NOT EXISTS presencas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                matricula_id INTEGER NOT NULL,
                data_aula TEXT NOT NULL,
                presente INTEGER NOT NULL DEFAULT 1 CHECK (presente IN (0,1)),
                observacao TEXT,
                registrado_em TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                FOREIGN KEY (matricula_id) REFERENCES matriculas(id) ON DELETE CASCADE,
                UNIQUE(matricula_id, data_aula)
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_aluno_turma_sem_duplicidade
                ON matriculas(aluno_id, turma_id);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_um_vinculo_ativo_por_aluno
                ON matriculas(aluno_id) WHERE status = 'ATIVA';

            CREATE TRIGGER IF NOT EXISTS impedir_turma_lotada
            BEFORE INSERT ON matriculas
            WHEN NEW.status = 'ATIVA'
            BEGIN
                SELECT CASE
                    WHEN (SELECT COUNT(*) FROM matriculas
                          WHERE turma_id = NEW.turma_id AND status = 'ATIVA') >=
                         (SELECT capacidade FROM turmas WHERE id = NEW.turma_id)
                    THEN RAISE(ABORT, 'TURMA_LOTADA')
                END;
            END;

            CREATE TRIGGER IF NOT EXISTS impedir_reativacao_em_turma_lotada
            BEFORE UPDATE OF status, turma_id ON matriculas
            WHEN NEW.status = 'ATIVA'
            BEGIN
                SELECT CASE
                    WHEN (SELECT COUNT(*) FROM matriculas
                          WHERE turma_id = NEW.turma_id AND status = 'ATIVA' AND id <> NEW.id) >=
                         (SELECT capacidade FROM turmas WHERE id = NEW.turma_id)
                    THEN RAISE(ABORT, 'TURMA_LOTADA')
                END;
            END;

            CREATE VIEW IF NOT EXISTS vw_turmas_ocupacao AS
            SELECT t.id, t.turno, t.dias_semana, t.hora_inicio, t.hora_fim,
                   t.capacidade, COUNT(m.id) AS vagas_ocupadas,
                   t.capacidade - COUNT(m.id) AS vagas_restantes
            FROM turmas t
            LEFT JOIN matriculas m
                ON m.turma_id = t.id AND m.status = 'ATIVA'
            GROUP BY t.id, t.turno, t.dias_semana, t.hora_inicio, t.hora_fim, t.capacidade;
        """)

        turmas = [
            ('Manhã', 'Segunda e Quarta-feira', '08:00', '09:00'),
            ('Manhã', 'Segunda e Quarta-feira', '09:00', '10:00'),
            ('Manhã', 'Segunda e Quarta-feira', '10:00', '11:00'),
            ('Manhã', 'Segunda e Quarta-feira', '11:00', '12:00'),
            ('Tarde', 'Segunda e Quarta-feira', '14:00', '15:00'),
            ('Tarde', 'Segunda e Quarta-feira', '15:00', '16:00'),
            ('Tarde', 'Segunda e Quarta-feira', '16:00', '17:00'),
            ('Tarde', 'Segunda e Quarta-feira', '17:00', '18:00'),
            ('Manhã', 'Terça e Quinta-feira', '08:00', '09:00'),
            ('Manhã', 'Terça e Quinta-feira', '09:00', '10:00'),
            ('Manhã', 'Terça e Quinta-feira', '10:00', '11:00'),
            ('Manhã', 'Terça e Quinta-feira', '11:00', '12:00'),
            ('Tarde', 'Terça e Quinta-feira', '14:00', '15:00'),
            ('Tarde', 'Terça e Quinta-feira', '15:00', '16:00'),
            ('Tarde', 'Terça e Quinta-feira', '16:00', '17:00'),
            ('Tarde', 'Terça e Quinta-feira', '17:00', '18:00'),
        ]
        conn.executemany(
            "INSERT OR IGNORE INTO turmas (turno, dias_semana, hora_inicio, hora_fim, capacidade, ativa) VALUES (?, ?, ?, ?, 9, 1)",
            turmas
        )
        conn.commit()


def conectar():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def json_bytes(obj):
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")

def fmt_cpf(v):
    s = "".join(c for c in str(v or "") if c.isdigit())
    if len(s) == 11:
        return f"{s[:3]}.{s[3:6]}.{s[6:9]}-{s[9:]}"
    return str(v or "")

def fmt_tel(v):
    s = "".join(c for c in str(v or "") if c.isdigit())
    if len(s) == 11:
        return f"({s[:2]}) {s[2:7]}-{s[7:]}"
    if len(s) == 10:
        return f"({s[:2]}) {s[2:6]}-{s[6:]}"
    return str(v or "")

def esc(v):
    return html.escape(str(v or ""))

def pagina(titulo, corpo, extra_head=""):
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(titulo)}</title>
<style>
*{{box-sizing:border-box}}
body{{font-family:Arial,sans-serif;margin:0;background:#eef4f7;color:#0f172a}}
.wrap{{max-width:1200px;margin:0 auto;padding:22px}}
.topo{{background:#0f172a;color:#fff;padding:20px;border-radius:14px;margin-bottom:18px}}
.topo h1{{margin:0 0 6px}}
.actions{{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0}}
.btn{{display:inline-block;text-decoration:none;border:0;border-radius:10px;padding:10px 13px;font-weight:800;cursor:pointer;background:#2563eb;color:#fff;font-size:14px}}
.btn.secondary{{background:#0f172a}}
.btn.light{{background:#fff;color:#0f172a;border:1px solid #cbd5e1}}
.btn.warn{{background:#d97706}}
.btn.danger{{background:#b91c1c}}
.btn:disabled{{opacity:.55;cursor:not-allowed}}
.cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:18px}}
.card{{background:#fff;border:1px solid #dbe4ea;border-radius:12px;padding:16px}}
.card strong{{display:block;font-size:26px;margin-bottom:4px}}
table{{width:100%;border-collapse:collapse;background:#fff;border-radius:12px;overflow:hidden}}
th,td{{padding:10px;border-bottom:1px solid #e5e7eb;text-align:left;vertical-align:top}}
th{{background:#f8fafc}}
tr:hover td{{background:#fafcff}}
.badge{{display:inline-block;padding:4px 8px;border-radius:999px;background:#e0f2fe;color:#075985;font-size:12px;font-weight:800}}
.badge.cancelada{{background:#fee2e2;color:#991b1b}}
.ficha{{max-width:800px;margin:0 auto;background:#fff;border:1px solid #dbe4ea;border-radius:14px;padding:24px}}
.ficha h1,.ficha h2{{text-align:center}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}
.campo{{border-bottom:1px dashed #94a3b8;padding:10px 0}}
.label{{font-size:12px;color:#64748b;text-transform:uppercase;font-weight:800}}
.valor{{font-size:16px;margin-top:3px}}
.form-card{{max-width:760px;margin:0 auto;background:#fff;border:1px solid #dbe4ea;border-radius:14px;padding:22px}}
.form-grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
.form-group{{margin-bottom:12px}}
.form-group.full{{grid-column:1/-1}}
label{{display:block;font-weight:800;margin-bottom:6px;color:#334155}}
input,select{{width:100%;min-height:44px;padding:10px 11px;border:1px solid #cbd5e1;border-radius:9px;font-size:15px;background:#fff}}
.notice{{padding:12px;border-radius:10px;background:#fffbeb;border:1px solid #fde68a;color:#92400e;margin:12px 0}}
.msg{{margin-top:12px;font-weight:800}}
@media(max-width:800px){{.cards,.grid2,.form-grid{{grid-template-columns:1fr}} table{{font-size:12px}} .wrap{{padding:12px}}}}
@media print{{
    body{{background:#fff}}
    .no-print{{display:none!important}}
    .wrap{{max-width:none;padding:0}}
    .topo{{background:#fff;color:#000;padding:0;border-radius:0}}
    table{{font-size:11px}}
    .ficha{{border:0;padding:0}}
}}
</style>
{extra_head}
</head>
<body><div class="wrap">{corpo}</div></body></html>"""

def buscar_aluno_com_matricula(conn, aluno_id):
    return conn.execute("""
        SELECT
            a.id, a.nome_completo, a.rg, a.cpf, a.contato, a.endereco,
            a.criado_em, a.atualizado_em,
            m.id AS matricula_id, m.status, m.data_matricula,
            t.id AS turma_id, t.turno, t.dias_semana, t.hora_inicio, t.hora_fim
        FROM alunos a
        JOIN matriculas m ON m.aluno_id = a.id
        JOIN turmas t ON t.id = m.turma_id
        WHERE a.id = ?
        ORDER BY CASE WHEN m.status='ATIVA' THEN 0 ELSE 1 END, m.id DESC
        LIMIT 1
    """, (aluno_id,)).fetchone()

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE_DIR), **kwargs)

    def responder_json(self, status, obj):
        data = json_bytes(obj)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def responder_html(self, status, text):
        data = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def responder_csv(self, filename, rows):
        output = io.StringIO()
        writer = csv.writer(output, delimiter=";")
        writer.writerows(rows)
        data = ("\ufeff" + output.getvalue()).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/":
            self.send_response(302)
            self.send_header("Location", "/" + HTML_FILE)
            self.end_headers()
            return

        if path == "/api/turmas":
            with conectar() as conn:
                rows = conn.execute("""
                    SELECT id, turno, dias_semana, hora_inicio, hora_fim,
                           capacidade, vagas_ocupadas, vagas_restantes
                    FROM vw_turmas_ocupacao
                    ORDER BY
                        CASE turno WHEN 'Manhã' THEN 1 ELSE 2 END,
                        CASE dias_semana WHEN 'Segunda e Quarta-feira' THEN 1 ELSE 2 END,
                        hora_inicio
                """).fetchall()
            self.responder_json(200, [dict(r) for r in rows])
            return

        if path == "/admin":
            with conectar() as conn:
                alunos = conn.execute("""
                    SELECT
                        a.id, a.nome_completo, a.cpf,
                        m.status, t.turno, t.dias_semana, t.hora_inicio, t.hora_fim
                    FROM matriculas m
                    JOIN alunos a ON a.id = m.aluno_id
                    JOIN turmas t ON t.id = m.turma_id
                    WHERE m.id = (
                        SELECT m2.id
                        FROM matriculas m2
                        WHERE m2.aluno_id = a.id
                        ORDER BY CASE WHEN m2.status='ATIVA' THEN 0 ELSE 1 END, m2.id DESC
                        LIMIT 1
                    )
                    ORDER BY CASE WHEN m.status='ATIVA' THEN 0 ELSE 1 END, a.nome_completo
                """).fetchall()

                resumo = conn.execute("""
                    SELECT SUM(capacidade) capacidade,
                           SUM(vagas_ocupadas) ocupadas,
                           SUM(vagas_restantes) restantes
                    FROM vw_turmas_ocupacao
                """).fetchone()

                ativos = conn.execute("""
                    SELECT COUNT(*) FROM matriculas WHERE status='ATIVA'
                """).fetchone()[0]

            linhas = []
            for a in alunos:
                status_class = "badge" if a["status"] == "ATIVA" else "badge cancelada"
                cancelar_btn = (
                    f'<button class="btn warn" onclick="cancelarMatricula({a["id"]}, {json.dumps(a["nome_completo"])})">Cancelar matrícula</button>'
                    if a["status"] == "ATIVA"
                    else '<button class="btn warn" disabled>Matrícula cancelada</button>'
                )
                linhas.append(f"""
                <tr>
                    <td>{esc(a['nome_completo'])}</td>
                    <td>{esc(fmt_cpf(a['cpf']))}</td>
                    <td>{esc(a['turno'])}</td>
                    <td>{esc(a['dias_semana'])}</td>
                    <td>{esc(a['hora_inicio'])}–{esc(a['hora_fim'])}</td>
                    <td><span class="{status_class}">{esc(a['status'])}</span></td>
                    <td class="no-print">
                        <div class="actions" style="margin:0">
                            <a class="btn light" href="/ficha/{a['id']}">Ficha</a>
                            <a class="btn secondary" href="/editar/{a['id']}">Editar</a>
                            {cancelar_btn}
                            <button class="btn danger" onclick="excluirAluno({a['id']}, {json.dumps(a["nome_completo"])})">Excluir definitivamente</button>
                        </div>
                    </td>
                </tr>""")

            corpo = f"""
            <div class="topo">
                <h1>Gestão de inscrições</h1>
                <div>Curso de Informática · CIDADE </div>
            </div>

            <div class="cards">
                <div class="card"><strong>{ativos}</strong>matrículas ativas</div>
                <div class="card"><strong>{resumo['ocupadas'] or 0}</strong>vagas ocupadas</div>
                <div class="card"><strong>{resumo['restantes'] or 0}</strong>vagas restantes de {resumo['capacidade'] or 0}</div>
            </div>

            <div class="actions no-print">
                <a class="btn" href="/relatorio-geral" target="_blank">Relatório Geral</a>
                <a class="btn secondary" href="/relatorio.csv">Baixar CSV</a>
                <a class="btn light" href="/">Nova inscrição</a>
            </div>

            <div class="notice no-print">
                <strong>Cancelar matrícula</strong> mantém o aluno no histórico e libera a vaga.
                <strong>Excluir definitivamente</strong> apaga o aluno, suas matrículas e presenças do banco.
            </div>

            <table>
                <thead>
                    <tr>
                        <th>Aluno</th><th>CPF</th><th>Turno</th><th>Dias</th>
                        <th>Horário</th><th>Status</th><th class="no-print">Ações</th>
                    </tr>
                </thead>
                <tbody>{''.join(linhas)}</tbody>
            </table>

            <script>
            async function cancelarMatricula(id, nome) {{
                if (!confirm(`Cancelar a matrícula de ${{nome}}?\\n\\nO aluno continuará no histórico e a vaga será liberada.`)) return;
                const r = await fetch(`/api/alunos/${{id}}/cancelar`, {{method:'POST'}});
                const j = await r.json();
                if (!r.ok) return alert(j.erro || 'Não foi possível cancelar.');
                alert('Matrícula cancelada com sucesso.');
                location.reload();
            }}

            async function excluirAluno(id, nome) {{
                const primeira = confirm(
                    `EXCLUSÃO DEFINITIVA\\n\\nVocê realmente deseja excluir ${{nome}} do banco?\\n\\n` +
                    `Isso apagará também matrícula(s) e presença(s).`
                );
                if (!primeira) return;

                const digitado = prompt(`Para confirmar a exclusão definitiva, digite EXCLUIR:`);
                if (digitado !== 'EXCLUIR') {{
                    alert('Exclusão cancelada.');
                    return;
                }}

                const r = await fetch(`/api/alunos/${{id}}/excluir`, {{method:'POST'}});
                const j = await r.json();
                if (!r.ok) return alert(j.erro || 'Não foi possível excluir.');
                alert('Aluno excluído definitivamente.');
                location.reload();
            }}
            </script>
            """
            self.responder_html(200, pagina("Gestão de inscrições", corpo))
            return

        if path.startswith("/editar/"):
            try:
                aluno_id = int(path.split("/")[-1])
            except ValueError:
                self.responder_html(400, pagina("Erro", "<p>ID inválido.</p>"))
                return

            with conectar() as conn:
                a = buscar_aluno_com_matricula(conn, aluno_id)
                turmas = conn.execute("""
                    SELECT id, turno, dias_semana, hora_inicio, hora_fim,
                           capacidade, vagas_ocupadas, vagas_restantes
                    FROM vw_turmas_ocupacao
                    ORDER BY
                        CASE turno WHEN 'Manhã' THEN 1 ELSE 2 END,
                        CASE dias_semana WHEN 'Segunda e Quarta-feira' THEN 1 ELSE 2 END,
                        hora_inicio
                """).fetchall()

            if not a:
                self.responder_html(404, pagina("Aluno não encontrado", "<p>Aluno não encontrado.</p>"))
                return

            opcoes = []
            for t in turmas:
                # A turma atual continua selecionável mesmo se estiver lotada,
                # pois o aluno já ocupa uma vaga nela.
                atual = t["id"] == a["turma_id"] and a["status"] == "ATIVA"
                bloqueada = t["vagas_restantes"] <= 0 and not atual
                selected = " selected" if atual else ""
                disabled = " disabled" if bloqueada else ""
                detalhe = "LOTADA" if bloqueada else f'{t["vagas_restantes"]} vaga(s)'
                if atual:
                    detalhe = "turma atual"
                opcoes.append(
                    f'<option value="{t["id"]}"{selected}{disabled}>'
                    f'{esc(t["turno"])} · {esc(t["dias_semana"])} · '
                    f'{esc(t["hora_inicio"])}–{esc(t["hora_fim"])} — {detalhe}</option>'
                )

            corpo = f"""
            <div class="topo">
                <h1>Editar aluno</h1>
                <div>{esc(a['nome_completo'])}</div>
            </div>

            <div class="form-card">
                <form id="formEditar">
                    <div class="form-grid">
                        <div class="form-group full">
                            <label>Nome completo</label>
                            <input id="nome" value="{esc(a['nome_completo'])}" required>
                        </div>
                        <div class="form-group">
                            <label>RG</label>
                            <input id="rg" value="{esc(a['rg'])}" required>
                        </div>
                        <div class="form-group">
                            <label>CPF</label>
                            <input id="cpf" value="{esc(a['cpf'])}" required>
                        </div>
                        <div class="form-group">
                            <label>Contato</label>
                            <input id="contato" value="{esc(a['contato'])}" required>
                        </div>
                        <div class="form-group full">
                            <label>Endereço</label>
                            <input id="endereco" value="{esc(a['endereco'])}" required>
                        </div>
                        <div class="form-group full">
                            <label>Turma</label>
                            <select id="turma_id" required>
                                {''.join(opcoes)}
                            </select>
                        </div>
                    </div>

                    <div class="notice">
                        Ao mudar a turma, o sistema verifica as vagas antes de salvar.
                        Se a matrícula estiver cancelada, editar os dados não a reativa automaticamente.
                    </div>

                    <div class="actions">
                        <button class="btn" type="submit">Salvar alterações</button>
                        <a class="btn light" href="/admin">Cancelar</a>
                    </div>
                    <div class="msg" id="msg"></div>
                </form>
            </div>

            <script>
            function digits(v) {{ return (v || '').replace(/\\D/g,''); }}

            document.getElementById('formEditar').addEventListener('submit', async (e) => {{
                e.preventDefault();
                const payload = {{
                    nome_completo: document.getElementById('nome').value.trim(),
                    rg: digits(document.getElementById('rg').value),
                    cpf: digits(document.getElementById('cpf').value),
                    contato: digits(document.getElementById('contato').value),
                    endereco: document.getElementById('endereco').value.trim(),
                    turma_id: Number(document.getElementById('turma_id').value)
                }};

                const msg = document.getElementById('msg');
                msg.textContent = 'Salvando...';

                const r = await fetch('/api/alunos/{aluno_id}/editar', {{
                    method:'POST',
                    headers:{{'Content-Type':'application/json'}},
                    body:JSON.stringify(payload)
                }});
                const j = await r.json();

                if (!r.ok) {{
                    msg.style.color = '#b91c1c';
                    msg.textContent = j.erro || 'Não foi possível salvar.';
                    return;
                }}

                msg.style.color = '#166534';
                msg.textContent = 'Alterações salvas com sucesso.';
                setTimeout(() => location.href='/admin', 700);
            }});
            </script>
            """
            self.responder_html(200, pagina("Editar aluno", corpo))
            return

        if path == "/relatorio-geral":
            with conectar() as conn:
                alunos = conn.execute("""
                    SELECT
                        a.nome_completo, a.rg, a.cpf, a.contato, a.endereco,
                        m.status, t.turno, t.dias_semana, t.hora_inicio, t.hora_fim
                    FROM matriculas m
                    JOIN alunos a ON a.id = m.aluno_id
                    JOIN turmas t ON t.id = m.turma_id
                    ORDER BY
                        CASE m.status WHEN 'ATIVA' THEN 0 ELSE 1 END,
                        CASE t.turno WHEN 'Manhã' THEN 1 ELSE 2 END,
                        CASE t.dias_semana WHEN 'Segunda e Quarta-feira' THEN 1 ELSE 2 END,
                        t.hora_inicio, a.nome_completo
                """).fetchall()

                turmas = conn.execute("""
                    SELECT turno, dias_semana, hora_inicio, hora_fim,
                           capacidade, vagas_ocupadas, vagas_restantes
                    FROM vw_turmas_ocupacao
                    ORDER BY
                        CASE turno WHEN 'Manhã' THEN 1 ELSE 2 END,
                        CASE dias_semana WHEN 'Segunda e Quarta-feira' THEN 1 ELSE 2 END,
                        hora_inicio
                """).fetchall()

            corpo = """
            <div class="topo">
                <h1>RELATÓRIO GERAL DE INSCRIÇÕES</h1>
                <div>Curso de Informática</div>
            </div>
            <div class="actions no-print">
                <button class="btn" onclick="window.print()">Imprimir / Salvar em PDF</button>
                <a class="btn light" href="/admin">Voltar</a>
            </div>
            <h2>Alunos cadastrados</h2>
            <table>
                <thead><tr><th>Nome</th><th>RG</th><th>CPF</th><th>Contato</th><th>Turma</th><th>Status</th></tr></thead>
                <tbody>
            """
            for a in alunos:
                corpo += f"""
                <tr>
                    <td>{esc(a['nome_completo'])}</td>
                    <td>{esc(a['rg'])}</td>
                    <td>{esc(fmt_cpf(a['cpf']))}</td>
                    <td>{esc(fmt_tel(a['contato']))}</td>
                    <td>{esc(a['turno'])} · {esc(a['dias_semana'])} · {esc(a['hora_inicio'])}–{esc(a['hora_fim'])}</td>
                    <td>{esc(a['status'])}</td>
                </tr>"""
            corpo += """
                </tbody>
            </table>
            <h2 style="margin-top:28px">Ocupação das turmas</h2>
            <table>
                <thead><tr><th>Turno</th><th>Dias</th><th>Horário</th><th>Capacidade</th><th>Ocupadas</th><th>Restantes</th></tr></thead>
                <tbody>
            """
            for t in turmas:
                corpo += f"""
                <tr>
                    <td>{esc(t['turno'])}</td>
                    <td>{esc(t['dias_semana'])}</td>
                    <td>{esc(t['hora_inicio'])}–{esc(t['hora_fim'])}</td>
                    <td>{t['capacidade']}</td>
                    <td>{t['vagas_ocupadas']}</td>
                    <td>{t['vagas_restantes']}</td>
                </tr>"""
            corpo += "</tbody></table>"
            self.responder_html(200, pagina("Relatório Geral", corpo))
            return

        if path == "/relatorio.csv":
            with conectar() as conn:
                rows = conn.execute("""
                    SELECT
                        a.nome_completo, a.rg, a.cpf, a.contato, a.endereco,
                        t.turno, t.dias_semana, t.hora_inicio, t.hora_fim,
                        m.status
                    FROM matriculas m
                    JOIN alunos a ON a.id = m.aluno_id
                    JOIN turmas t ON t.id = m.turma_id
                    ORDER BY a.nome_completo
                """).fetchall()

            csv_rows = [[
                "Nome Completo","RG","CPF","Contato","Endereço",
                "Turno","Dias","Hora Início","Hora Fim","Status"
            ]]
            for r in rows:
                csv_rows.append([
                    r["nome_completo"], r["rg"], fmt_cpf(r["cpf"]),
                    fmt_tel(r["contato"]), r["endereco"], r["turno"],
                    r["dias_semana"], r["hora_inicio"], r["hora_fim"], r["status"]
                ])
            self.responder_csv("relatorio_alunos.csv", csv_rows)
            return

        if path.startswith("/ficha/"):
            try:
                aluno_id = int(path.split("/")[-1])
            except ValueError:
                self.responder_html(400, "ID inválido")
                return

            with conectar() as conn:
                a = buscar_aluno_com_matricula(conn, aluno_id)

            if not a:
                self.responder_html(404, "Aluno não encontrado")
                return

            corpo = f"""
            <div class="actions no-print">
                <button class="btn" onclick="window.print()">Imprimir / Salvar em PDF</button>
                <a class="btn secondary" href="/editar/{a['id']}">Editar</a>
                <a class="btn light" href="/admin">Voltar</a>
            </div>
            <div class="ficha">
                <h1>FICHA INDIVIDUAL DE INSCRIÇÃO</h1>
                <h2>Curso de Informática </h2>

                <div class="campo"><div class="label">Nome completo</div><div class="valor">{esc(a['nome_completo'])}</div></div>
                <div class="grid2">
                    <div class="campo"><div class="label">RG</div><div class="valor">{esc(a['rg'])}</div></div>
                    <div class="campo"><div class="label">CPF</div><div class="valor">{esc(fmt_cpf(a['cpf']))}</div></div>
                    <div class="campo"><div class="label">Contato</div><div class="valor">{esc(fmt_tel(a['contato']))}</div></div>
                    <div class="campo"><div class="label">Status</div><div class="valor">{esc(a['status'])}</div></div>
                </div>
                <div class="campo"><div class="label">Endereço</div><div class="valor">{esc(a['endereco'])}</div></div>
                <div class="grid2">
                    <div class="campo"><div class="label">Turno</div><div class="valor">{esc(a['turno'])}</div></div>
                    <div class="campo"><div class="label">Dias</div><div class="valor">{esc(a['dias_semana'])}</div></div>
                    <div class="campo"><div class="label">Horário</div><div class="valor">{esc(a['hora_inicio'])} às {esc(a['hora_fim'])}</div></div>
                    <div class="campo"><div class="label">Data da matrícula</div><div class="valor">{esc(a['data_matricula'])}</div></div>
                </div>

                <div style="margin-top:38px;display:grid;grid-template-columns:1fr 1fr;gap:40px">
                    <div style="border-top:1px solid #000;text-align:center;padding-top:6px">Assinatura do aluno/responsável</div>
                    <div style="border-top:1px solid #000;text-align:center;padding-top:6px">Sistema</div>
                </div>
            </div>
            """
            self.responder_html(200, pagina(f"Ficha - {a['nome_completo']}", corpo))
            return

        super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/api/inscricoes":
            return self.salvar_nova_inscricao()

        if path.startswith("/api/alunos/") and path.endswith("/editar"):
            try:
                aluno_id = int(path.split("/")[3])
            except (ValueError, IndexError):
                self.responder_json(400, {"erro": "ID inválido."})
                return
            return self.editar_aluno(aluno_id)

        if path.startswith("/api/alunos/") and path.endswith("/cancelar"):
            try:
                aluno_id = int(path.split("/")[3])
            except (ValueError, IndexError):
                self.responder_json(400, {"erro": "ID inválido."})
                return
            return self.cancelar_matricula(aluno_id)

        if path.startswith("/api/alunos/") and path.endswith("/excluir"):
            try:
                aluno_id = int(path.split("/")[3])
            except (ValueError, IndexError):
                self.responder_json(400, {"erro": "ID inválido."})
                return
            return self.excluir_aluno(aluno_id)

        self.responder_json(404, {"erro": "Rota não encontrada."})

    def ler_json(self):
        tamanho = int(self.headers.get("Content-Length", "0"))
        if tamanho <= 0:
            return {}
        return json.loads(self.rfile.read(tamanho).decode("utf-8"))

    def salvar_nova_inscricao(self):
        try:
            dados = self.ler_json()
            obrigatorios = [
                "nome_completo", "rg", "cpf", "contato", "endereco",
                "turno", "dias_semana", "hora_inicio"
            ]
            faltando = [c for c in obrigatorios if not str(dados.get(c, "")).strip()]
            if faltando:
                self.responder_json(400, {"erro": "Preencha todos os campos obrigatórios."})
                return

            nome = str(dados["nome_completo"]).strip()
            rg = "".join(c for c in str(dados["rg"]) if c.isdigit())
            cpf = "".join(c for c in str(dados["cpf"]) if c.isdigit())
            contato = "".join(c for c in str(dados["contato"]) if c.isdigit())
            endereco = str(dados["endereco"]).strip()
            turno = str(dados["turno"]).strip()
            dias = str(dados["dias_semana"]).strip()
            hora = str(dados["hora_inicio"]).strip()

            if turno not in ("Manhã", "Tarde"):
                self.responder_json(400, {"erro": "Turno inválido."})
                return
            if dias not in ("Segunda e Quarta-feira", "Terça e Quinta-feira"):
                self.responder_json(400, {"erro": "Dias da semana inválidos."})
                return

            with conectar() as conn:
                duplicado = conn.execute("""
                    SELECT id, nome_completo FROM alunos
                    WHERE rg = ? OR cpf = ?
                    LIMIT 1
                """, (rg, cpf)).fetchone()

                if duplicado:
                    self.responder_json(409, {"erro": f"Aluno já cadastrado: {duplicado['nome_completo']}."})
                    return

                turma = conn.execute("""
                    SELECT id, capacidade
                    FROM turmas
                    WHERE turno = ? AND dias_semana = ? AND hora_inicio = ? AND ativa = 1
                    LIMIT 1
                """, (turno, dias, hora)).fetchone()

                if not turma:
                    self.responder_json(400, {"erro": "Turma não encontrada."})
                    return

                ocupadas = conn.execute("""
                    SELECT COUNT(*) FROM matriculas
                    WHERE turma_id = ? AND status = 'ATIVA'
                """, (turma["id"],)).fetchone()[0]

                if ocupadas >= turma["capacidade"]:
                    self.responder_json(409, {"erro": "Turma lotada. Escolha outro horário."})
                    return

                cur = conn.execute("""
                    INSERT INTO alunos (nome_completo, rg, cpf, contato, endereco)
                    VALUES (?, ?, ?, ?, ?)
                """, (nome, rg, cpf, contato, endereco))
                aluno_id = cur.lastrowid

                conn.execute("""
                    INSERT INTO matriculas (aluno_id, turma_id, status)
                    VALUES (?, ?, 'ATIVA')
                """, (aluno_id, turma["id"]))
                conn.commit()

                ocupadas_depois = conn.execute("""
                    SELECT COUNT(*) FROM matriculas
                    WHERE turma_id = ? AND status = 'ATIVA'
                """, (turma["id"],)).fetchone()[0]

            self.responder_json(201, {
                "ok": True,
                "aluno_id": aluno_id,
                "turma_id": turma["id"],
                "vagas_ocupadas": ocupadas_depois,
                "vagas_restantes": turma["capacidade"] - ocupadas_depois
            })

        except sqlite3.IntegrityError as exc:
            msg = str(exc)
            if "TURMA_LOTADA" in msg:
                self.responder_json(409, {"erro": "Turma lotada."})
            elif "UNIQUE" in msg:
                self.responder_json(409, {"erro": "RG ou CPF já cadastrado."})
            else:
                self.responder_json(400, {"erro": "Não foi possível salvar a inscrição."})
        except Exception as exc:
            print("ERRO:", repr(exc))
            self.responder_json(500, {"erro": "Erro interno ao salvar."})

    def editar_aluno(self, aluno_id):
        try:
            dados = self.ler_json()
            obrigatorios = ["nome_completo", "rg", "cpf", "contato", "endereco", "turma_id"]
            if any(not str(dados.get(c, "")).strip() for c in obrigatorios):
                self.responder_json(400, {"erro": "Preencha todos os campos obrigatórios."})
                return

            nome = str(dados["nome_completo"]).strip()
            rg = "".join(c for c in str(dados["rg"]) if c.isdigit())
            cpf = "".join(c for c in str(dados["cpf"]) if c.isdigit())
            contato = "".join(c for c in str(dados["contato"]) if c.isdigit())
            endereco = str(dados["endereco"]).strip()
            turma_id_nova = int(dados["turma_id"])

            with conectar() as conn:
                atual = buscar_aluno_com_matricula(conn, aluno_id)
                if not atual:
                    self.responder_json(404, {"erro": "Aluno não encontrado."})
                    return

                duplicado = conn.execute("""
                    SELECT id, nome_completo
                    FROM alunos
                    WHERE id <> ? AND (rg = ? OR cpf = ?)
                    LIMIT 1
                """, (aluno_id, rg, cpf)).fetchone()
                if duplicado:
                    self.responder_json(409, {"erro": f"RG ou CPF já pertence a {duplicado['nome_completo']}."})
                    return

                turma = conn.execute("""
                    SELECT id, capacidade, ativa FROM turmas WHERE id = ?
                """, (turma_id_nova,)).fetchone()
                if not turma or turma["ativa"] != 1:
                    self.responder_json(400, {"erro": "Turma inválida ou inativa."})
                    return

                if atual["status"] == "ATIVA" and turma_id_nova != atual["turma_id"]:
                    ocupadas = conn.execute("""
                        SELECT COUNT(*) FROM matriculas
                        WHERE turma_id = ? AND status='ATIVA'
                    """, (turma_id_nova,)).fetchone()[0]
                    if ocupadas >= turma["capacidade"]:
                        self.responder_json(409, {"erro": "A nova turma está lotada."})
                        return

                conn.execute("""
                    UPDATE alunos
                    SET nome_completo=?, rg=?, cpf=?, contato=?, endereco=?,
                        atualizado_em=datetime('now','localtime')
                    WHERE id=?
                """, (nome, rg, cpf, contato, endereco, aluno_id))

                # Se a matrícula exibida estiver ativa, permite trocar de turma.
                # Matrícula cancelada continua cancelada; altera apenas a turma histórica selecionada.
                conn.execute("""
                    UPDATE matriculas SET turma_id=? WHERE id=?
                """, (turma_id_nova, atual["matricula_id"]))

                conn.commit()

            self.responder_json(200, {"ok": True})

        except sqlite3.IntegrityError as exc:
            msg = str(exc)
            if "TURMA_LOTADA" in msg:
                self.responder_json(409, {"erro": "A nova turma está lotada."})
            elif "UNIQUE" in msg:
                self.responder_json(409, {"erro": "RG ou CPF já cadastrado."})
            else:
                self.responder_json(400, {"erro": "Não foi possível salvar as alterações."})
        except Exception as exc:
            print("ERRO EDITAR:", repr(exc))
            self.responder_json(500, {"erro": "Erro interno ao editar."})

    def cancelar_matricula(self, aluno_id):
        try:
            with conectar() as conn:
                m = conn.execute("""
                    SELECT id FROM matriculas
                    WHERE aluno_id=? AND status='ATIVA'
                    ORDER BY id DESC LIMIT 1
                """, (aluno_id,)).fetchone()
                if not m:
                    self.responder_json(409, {"erro": "Esse aluno não possui matrícula ativa."})
                    return

                conn.execute("""
                    UPDATE matriculas
                    SET status='CANCELADA',
                        observacao=COALESCE(observacao || ' | ', '') || 'Cancelada pela área administrativa'
                    WHERE id=?
                """, (m["id"],))
                conn.commit()

            self.responder_json(200, {"ok": True})
        except Exception as exc:
            print("ERRO CANCELAR:", repr(exc))
            self.responder_json(500, {"erro": "Erro interno ao cancelar matrícula."})

    def excluir_aluno(self, aluno_id):
        try:
            with conectar() as conn:
                existe = conn.execute("SELECT nome_completo FROM alunos WHERE id=?", (aluno_id,)).fetchone()
                if not existe:
                    self.responder_json(404, {"erro": "Aluno não encontrado."})
                    return

                # Apaga presenças ligadas às matrículas do aluno.
                conn.execute("""
                    DELETE FROM presencas
                    WHERE matricula_id IN (
                        SELECT id FROM matriculas WHERE aluno_id=?
                    )
                """, (aluno_id,))

                conn.execute("DELETE FROM matriculas WHERE aluno_id=?", (aluno_id,))
                conn.execute("DELETE FROM alunos WHERE id=?", (aluno_id,))
                conn.commit()

            self.responder_json(200, {"ok": True})
        except Exception as exc:
            print("ERRO EXCLUIR:", repr(exc))
            self.responder_json(500, {"erro": "Erro interno ao excluir definitivamente."})

def abrir_navegador():
    time.sleep(0.8)
    webbrowser.open(f"http://{HOST}:{PORT}/")

if __name__ == "__main__":
    inicializar_banco()

    print("=" * 64)
    print("Sistema de Inscrições")
    print(f"Banco:   {DB_PATH}")
    print(f"Cadastro: http://{HOST}:{PORT}/")
    print(f"Gestão:   http://{HOST}:{PORT}/admin")
    print("Para encerrar, pressione Ctrl+C.")
    print("=" * 64)

    threading.Thread(target=abrir_navegador, daemon=True).start()
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
