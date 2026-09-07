# Sistema de Inscrições - Curso de Informática

Sistema local para cadastro de alunos, controle de turmas, gestão de matrículas e geração de relatórios.

## Como executar

1. Tenha o Python 3 instalado.
2. Coloque todos os arquivos desta pasta no mesmo diretório.
3. No Windows, execute `INICIAR.bat`.
4. O navegador será aberto automaticamente.

Endereços locais:

- Cadastro: http://127.0.0.1:8765/
- Gestão: http://127.0.0.1:8765/admin

## Funcionalidades

- Cadastro de alunos.
- Controle de vagas por turma.
- Validação de RG e CPF duplicados.
- Edição de cadastro e turma.
- Cancelamento de matrícula.
- Exclusão definitiva com confirmação.
- Ficha individual para impressão/PDF.
- Relatório geral.
- Exportação para CSV.

## Banco de dados

O SQLite é criado automaticamente na primeira execução, junto com as turmas padrão. Nenhum cadastro pessoal existente é incluído no projeto.

O arquivo `curso_informatica.db` é ignorado pelo Git para evitar o envio de dados locais para o repositório.

## Estrutura

- `servidor.py` — servidor HTTP e API.
- `inscricao.html` — tela de cadastro.
- `INICIAR.bat` — inicialização no Windows.
- `README.md` — documentação.
- `.gitignore` — arquivos locais que não devem ir para o repositório.
