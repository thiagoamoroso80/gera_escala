# app/main.py - SISTEMA WEB COMPLETO PARA HOSPEDAGEM
import os
from fastapi import FastAPI, Request, Depends, Form, HTTPException, Response
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import secrets
from datetime import datetime, date, timedelta
from pathlib import Path
import json
import pandas as pd
from typing import Optional
import sqlite3
import logging

# Configuração
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Criar diretórios
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
TEMPLATES_DIR = BASE_DIR / "frontend"
STATIC_DIR = BASE_DIR / "frontend" / "static"

# Inicializar app
app = FastAPI(title="Sistema de Escalas Web", version="3.0")

# Configurar templates e static files
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Sistema de autenticação simples
security = HTTPBasic()
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASSWORD", "Escala@123")  # Usa variável de ambiente
#ADMIN_PASS = "escala123"  # Mude isso em produção!

# Usuário visualizador padrão (pode ser alterado via variáveis de ambiente)
VIEWER_USER = os.getenv("VIEWER_USER", "visualizador")
VIEWER_PASS = os.getenv("VIEWER_PASSWORD", "visual123")

def verificar_credenciais_completas(credentials: HTTPBasicCredentials = Depends(security)):
    """Verifica credenciais para admin ou visualizador"""
    
    # Verificar se é admin
    usuario_admin_correto = secrets.compare_digest(credentials.username, ADMIN_USER)
    senha_admin_correto = secrets.compare_digest(credentials.password, ADMIN_PASS)
    
    # Verificar se é visualizador
    usuario_viewer_correto = secrets.compare_digest(credentials.username, VIEWER_USER)
    senha_viewer_correto = secrets.compare_digest(credentials.password, VIEWER_PASS)
    
    if not (usuario_admin_correto and senha_admin_correto) and not (usuario_viewer_correto and senha_viewer_correto):
        raise HTTPException(
            status_code=401,
            detail="Credenciais inválidas",
            headers={"WWW-Authenticate": "Basic"},
        )
    
    # Retorna tipo de usuário e nome
    if usuario_admin_correto and senha_admin_correto:
        return {"tipo": "admin", "usuario": credentials.username}
    else:
        return {"tipo": "viewer", "usuario": credentials.username}

# ==================== DEPENDÊNCIAS PARA PERMISSÕES ====================
def verificar_admin(credenciais: dict = Depends(verificar_credenciais_completas)):
    """Verifica se o usuário é administrador"""
    if credenciais["tipo"] != "admin":
        raise HTTPException(
            status_code=403,
            detail="Acesso negado. Apenas administradores podem acessar esta funcionalidade."
        )
    return credenciais

def verificar_viewer(credenciais: dict = Depends(verificar_credenciais_completas)):
    """Verifica se o usuário é visualizador"""
    if credenciais["tipo"] != "viewer":
        raise HTTPException(
            status_code=403,
            detail="Acesso negado. Esta funcionalidade é apenas para visualizadores."
        )
    return credenciais

def qualquer_usuario(credenciais: dict = Depends(verificar_credenciais_completas)):
    """Permite acesso tanto para admin quanto viewer"""
    return credenciais

# ==================== BANCO DE DADOS SQLite ====================
def init_database():
    """Inicializa o banco de dados SQLite"""
    db_path = DATA_DIR / "escalas.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Tabela de participantes
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS participantes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        telefone TEXT,
        email TEXT,
        instituicao TEXT NOT NULL,
        grupo_lar TEXT,
        grupo_tenda TEXT,
        ativo BOOLEAN DEFAULT 1,
        observacoes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Tabela de grupos Lar
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS grupos_lar (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        dia_defumacao TEXT NOT NULL,
        ordem_rotacao INTEGER,
        participantes_ids TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Tabela de grupos Tenda
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS grupos_tenda (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        dia_preferencial TEXT,
        participantes_ids TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Tabela de escalas Lar
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS escalas_lar (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        data DATE NOT NULL,
        semana_ano INTEGER,
        grupo_id INTEGER,
        grupo_nome TEXT,
        participantes_ids TEXT,
        status TEXT DEFAULT 'pendente',
        observacoes TEXT,
        ano INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Tabela de escalas Tenda
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS escalas_tenda (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        data DATE NOT NULL,
        grupo_id INTEGER,
        grupo_nome TEXT,
        participantes_ids TEXT,
        data_trabalho_mensal DATE,
        status TEXT DEFAULT 'pendente',
        observacoes TEXT,
        ano INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    conn.commit()
    conn.close()
    logger.info("Banco de dados inicializado")

# ==================== FUNÇÕES DO BANCO ====================
def get_db():
    """Retorna conexão com o banco"""
    db_path = DATA_DIR / "escalas.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # Para retornar dicionários
    return conn

# ==================== SISTEMA DE ESCALAS ====================
class SistemaEscalasWeb:
    def __init__(self):
        init_database()
        self.carregar_config()
    
    def carregar_config(self):
        """Carrega configurações"""
        config_path = DATA_DIR / "config.json"
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                self.config = json.load(f)
        else:
            self.config = {
                "ano_vigente": datetime.now().year,
                "regras": {
                    "lar": "sabado_ou_domingo_conforme_grupo",
                    "tenda": "apos_ultima_sexta_mes",
                    "impedimento": "mesmo_grupo_nao_pode_duas_escalas_mesmo_fds"
                }
            }
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
    
    # ==================== CRUD PARTICIPANTES ====================
    def adicionar_participante(self, dados):
        """Adiciona participante"""
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('''
        INSERT INTO participantes 
        (nome, telefone, email, instituicao, grupo_lar, grupo_tenda, observacoes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            dados['nome'],
            dados.get('telefone', ''),
            dados.get('email', ''),
            dados['instituicao'],
            dados.get('grupo_lar', ''),
            dados.get('grupo_tenda', ''),
            dados.get('observacoes', '')
        ))
        
        participante_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        # Atualizar grupos se necessário
        if dados.get('grupo_lar'):
            self._adicionar_participante_ao_grupo(
                participante_id, dados['grupo_lar'], 'lar'
            )
        
        if dados.get('grupo_tenda'):
            self._adicionar_participante_ao_grupo(
                participante_id, dados['grupo_tenda'], 'tenda'
            )
        
        return participante_id
    
    def _adicionar_participante_ao_grupo(self, participante_id, grupo_id, tipo):
        """Adiciona participante a um grupo"""
        conn = get_db()
        cursor = conn.cursor()
        
        if tipo == 'lar':
            cursor.execute('SELECT participantes_ids FROM grupos_lar WHERE id = ?', (grupo_id,))
        else:
            cursor.execute('SELECT participantes_ids FROM grupos_tenda WHERE id = ?', (grupo_id,))
        
        grupo = cursor.fetchone()
        if grupo:
            participantes = grupo['participantes_ids'] or ''
            if participantes:
                participantes += f",{participante_id}"
            else:
                participantes = str(participante_id)
            
            if tipo == 'lar':
                cursor.execute('''
                UPDATE grupos_lar SET participantes_ids = ? WHERE id = ?
                ''', (participantes, grupo_id))
            else:
                cursor.execute('''
                UPDATE grupos_tenda SET participantes_ids = ? WHERE id = ?
                ''', (participantes, grupo_id))
            
            conn.commit()
        
        conn.close()
    
    def listar_participantes(self):
        """Lista todos os participantes"""
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM participantes ORDER BY nome')
        participantes = [dict(row) for row in cursor.fetchall()]
        
        conn.close()
        return participantes
    
    def obter_participante(self, id):
        """Obtém um participante por ID"""
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM participantes WHERE id = ?', (id,))
        participante = cursor.fetchone()
        
        conn.close()
        return dict(participante) if participante else None
    
    def atualizar_participante(self, id, dados):
        """Atualiza participante"""
        conn = get_db()
        cursor = conn.cursor()
        
        # Primeiro, remover dos grupos antigos
        cursor.execute('SELECT grupo_lar, grupo_tenda FROM participantes WHERE id = ?', (id,))
        atual = cursor.fetchone()
        
        if atual:
            # Remover do grupo Lar antigo
            if atual['grupo_lar'] and atual['grupo_lar'] != dados.get('grupo_lar', ''):
                self._remover_participante_do_grupo(id, atual['grupo_lar'], 'lar')
            
            # Remover do grupo Tenda antigo
            if atual['grupo_tenda'] and atual['grupo_tenda'] != dados.get('grupo_tenda', ''):
                self._remover_participante_do_grupo(id, atual['grupo_tenda'], 'tenda')
        
        # Atualizar participante
        cursor.execute('''
        UPDATE participantes SET
        nome = ?, telefone = ?, email = ?, instituicao = ?,
        grupo_lar = ?, grupo_tenda = ?, ativo = ?, observacoes = ?
        WHERE id = ?
        ''', (
            dados['nome'],
            dados.get('telefone', ''),
            dados.get('email', ''),
            dados['instituicao'],
            dados.get('grupo_lar', ''),
            dados.get('grupo_tenda', ''),
            dados.get('ativo', 1),
            dados.get('observacoes', ''),
            id
        ))
        
        conn.commit()
        conn.close()
        
        # Adicionar aos novos grupos
        if dados.get('grupo_lar'):
            self._adicionar_participante_ao_grupo(id, dados['grupo_lar'], 'lar')
        
        if dados.get('grupo_tenda'):
            self._adicionar_participante_ao_grupo(id, dados['grupo_tenda'], 'tenda')
        
        return True
    
    def _remover_participante_do_grupo(self, participante_id, grupo_id, tipo):
        """Remove participante de um grupo"""
        conn = get_db()
        cursor = conn.cursor()
        
        if tipo == 'lar':
            cursor.execute('SELECT participantes_ids FROM grupos_lar WHERE id = ?', (grupo_id,))
        else:
            cursor.execute('SELECT participantes_ids FROM grupos_tenda WHERE id = ?', (grupo_id,))
        
        grupo = cursor.fetchone()
        if grupo and grupo['participantes_ids']:
            participantes = grupo['participantes_ids'].split(',')
            participantes = [p for p in participantes if p != str(participante_id)]
            
            if tipo == 'lar':
                cursor.execute('''
                UPDATE grupos_lar SET participantes_ids = ? WHERE id = ?
                ''', (','.join(participantes), grupo_id))
            else:
                cursor.execute('''
                UPDATE grupos_tenda SET participantes_ids = ? WHERE id = ?
                ''', (','.join(participantes), grupo_id))
            
            conn.commit()
        
        conn.close()
    
    def excluir_participante(self, id):
        """Exclui participante"""
        conn = get_db()
        cursor = conn.cursor()
        
        # Remover dos grupos primeiro
        cursor.execute('SELECT grupo_lar, grupo_tenda FROM participantes WHERE id = ?', (id,))
        participante = cursor.fetchone()
        
        if participante:
            if participante['grupo_lar']:
                self._remover_participante_do_grupo(id, participante['grupo_lar'], 'lar')
            
            if participante['grupo_tenda']:
                self._remover_participante_do_grupo(id, participante['grupo_tenda'], 'tenda')
        
        # Excluir participante
        cursor.execute('DELETE FROM participantes WHERE id = ?', (id,))
        conn.commit()
        conn.close()
        
        return True
    
    # ==================== CRUD GRUPOS ====================
    def adicionar_grupo_lar(self, dados):
        """Adiciona grupo Lar"""
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('''
        INSERT INTO grupos_lar (nome, dia_defumacao, ordem_rotacao, participantes_ids)
        VALUES (?, ?, ?, ?)
        ''', (
            dados['nome'],
            dados['dia_defumacao'],
            dados.get('ordem_rotacao', 1),
            dados.get('participantes_ids', '')
        ))
        
        grupo_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return grupo_id
    
    def adicionar_grupo_tenda(self, dados):
        """Adiciona grupo Tenda"""
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('''
        INSERT INTO grupos_tenda (nome, dia_preferencial, participantes_ids)
        VALUES (?, ?, ?)
        ''', (
            dados['nome'],
            dados.get('dia_preferencial', ''),
            dados.get('participantes_ids', '')
        ))
        
        grupo_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return grupo_id
    
    def listar_grupos_lar(self):
        """Lista grupos Lar"""
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM grupos_lar ORDER BY ordem_rotacao')
        grupos = [dict(row) for row in cursor.fetchall()]
        
        conn.close()
        return grupos
    
    def listar_grupos_tenda(self):
        """Lista grupos Tenda"""
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM grupos_tenda ORDER BY nome')
        grupos = [dict(row) for row in cursor.fetchall()]
        
        conn.close()
        return grupos
    
    # ==================== GERAÇÃO DE ESCALAS ====================
    def gerar_escala_anual(self, ano=None):
        """Gera escala anual"""
        if ano is None:
            ano = self.config['ano_vigente']
        
        logger.info(f"Gerando escala anual {ano}...")
        
        # Limpar escalas antigas
        self._limpar_escalas(ano)
        
        # Obter grupos
        grupos_lar = self.listar_grupos_lar()
        grupos_tenda = self.listar_grupos_tenda()
        
        if not grupos_lar:
            raise Exception("Nenhum grupo Lar cadastrado")
        
        # Obter finais de semana
        finais_semana = self._obter_finais_semana(ano)
        
        # Gerar escalas
        for semana_idx, semana in enumerate(finais_semana):
            # Grupo do Lar (rotação)
            grupo_idx = semana_idx % len(grupos_lar)
            grupo_lar = grupos_lar[grupo_idx]
            
            # Data da defumação
            dia_defumacao = grupo_lar.get('dia_defumacao', 'sabado')
            data_defumacao = semana['sabado'] if dia_defumacao == 'sabado' else semana['domingo']
            
            # Salvar defumação
            self._salvar_escala_lar({
                'data': data_defumacao,
                'semana_ano': semana_idx + 1,
                'grupo_id': grupo_lar['id'],
                'grupo_nome': grupo_lar['nome'],
                'participantes_ids': grupo_lar.get('participantes_ids', ''),
                'ano': ano,
                'observacoes': f'Dia: {dia_defumacao}'
            })
            
            # Verificar se é limpeza
            if self._eh_final_semana_limpeza(data_defumacao) and grupos_tenda:
                # Encontrar grupo disponível
                grupos_disponiveis = [g for g in grupos_tenda if g['id'] != grupo_lar['id']]
                
                if grupos_disponiveis:
                    mes = data_defumacao.month - 1
                    grupo_tenda = grupos_disponiveis[mes % len(grupos_disponiveis)]
                    
                    # Dia da limpeza
                    dia_limpeza = grupo_tenda.get('dia_preferencial', 'sabado' if dia_defumacao == 'domingo' else 'domingo')
                    data_limpeza = semana['sabado'] if dia_limpeza == 'sabado' else semana['domingo']
                    
                    # Data do trabalho
                    data_trabalho = self._obter_ultima_sexta(data_limpeza)
                    
                    # Salvar limpeza
                    self._salvar_escala_tenda({
                        'data': data_limpeza,
                        'grupo_id': grupo_tenda['id'],
                        'grupo_nome': grupo_tenda['nome'],
                        'participantes_ids': grupo_tenda.get('participantes_ids', ''),
                        'data_trabalho_mensal': data_trabalho,
                        'ano': ano,
                        'observacoes': f"Limpeza após trabalho"
                    })
        
        # Contar escalas geradas
        total_lar = self._contar_escalas_lar(ano)
        total_tenda = self._contar_escalas_tenda(ano)
        
        return {
            'ano': ano,
            'defumacoes': total_lar,
            'limpezas': total_tenda,
            'sucesso': True
        }
    
    def _obter_finais_semana(self, ano):
        """Retorna finais de semana do ano"""
        finais = []
        data = datetime(ano, 1, 1)
        
        # Primeiro sábado
        while data.weekday() != 5:
            data += timedelta(days=1)
        
        while data.year == ano:
            finais.append({
                'sabado': data.date(),
                'domingo': (data + timedelta(days=1)).date()
            })
            data += timedelta(days=7)
        
        return finais
    
    def _eh_final_semana_limpeza(self, data):
        """Verifica se é final de limpeza"""
        ultima_sexta = self._obter_ultima_sexta(data)
        sabado = ultima_sexta + timedelta(days=1)
        domingo = ultima_sexta + timedelta(days=2)
        
        return data == sabado or data == domingo
    
    def _obter_ultima_sexta(self, data):
        """Última sexta do mês"""
        ano = data.year
        mes = data.month
        
        if mes == 12:
            ultimo_dia = date(ano + 1, 1, 1) - timedelta(days=1)
        else:
            ultimo_dia = date(ano, mes + 1, 1) - timedelta(days=1)
        
        while ultimo_dia.weekday() != 4:
            ultimo_dia -= timedelta(days=1)
        
        return ultimo_dia
    
    def _limpar_escalas(self, ano):
        """Remove escalas do ano"""
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM escalas_lar WHERE ano = ?', (ano,))
        cursor.execute('DELETE FROM escalas_tenda WHERE ano = ?', (ano,))
        
        conn.commit()
        conn.close()
    
    def _salvar_escala_lar(self, dados):
        """Salva escala Lar"""
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('''
        INSERT INTO escalas_lar 
        (data, semana_ano, grupo_id, grupo_nome, participantes_ids, ano, observacoes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            dados['data'].isoformat(),
            dados['semana_ano'],
            dados['grupo_id'],
            dados['grupo_nome'],
            dados.get('participantes_ids', ''),
            dados['ano'],
            dados.get('observacoes', '')
        ))
        
        conn.commit()
        conn.close()
    
    def _salvar_escala_tenda(self, dados):
        """Salva escala Tenda"""
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('''
        INSERT INTO escalas_tenda 
        (data, grupo_id, grupo_nome, participantes_ids, data_trabalho_mensal, ano, observacoes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            dados['data'].isoformat(),
            dados['grupo_id'],
            dados['grupo_nome'],
            dados.get('participantes_ids', ''),
            dados['data_trabalho_mensal'].isoformat(),
            dados['ano'],
            dados.get('observacoes', '')
        ))
        
        conn.commit()
        conn.close()
    
    def _contar_escalas_lar(self, ano):
        """Conta escalas Lar"""
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) as total FROM escalas_lar WHERE ano = ?', (ano,))
        total = cursor.fetchone()['total']
        
        conn.close()
        return total
    
    def _contar_escalas_tenda(self, ano):
        """Conta escalas Tenda"""
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) as total FROM escalas_tenda WHERE ano = ?', (ano,))
        total = cursor.fetchone()['total']
        
        conn.close()
        return total
    
    def listar_escalas_lar(self, ano=None, limit=50):
        """Lista escalas Lar"""
        if ano is None:
            ano = self.config['ano_vigente']
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('''
        SELECT * FROM escalas_lar 
        WHERE ano = ? 
        ORDER BY data 
        LIMIT ?
        ''', (ano, limit))
        
        escalas = [dict(row) for row in cursor.fetchall()]
        
        # Formatar datas
        for escala in escalas:
            if escala.get('data'):
                data_obj = datetime.fromisoformat(escala['data'])
                escala['data_formatada'] = data_obj.strftime('%d/%m/%Y')
        
        conn.close()
        return escalas
    
    def listar_escalas_tenda(self, ano=None, limit=50):
        """Lista escalas Tenda"""
        if ano is None:
            ano = self.config['ano_vigente']
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('''
        SELECT * FROM escalas_tenda 
        WHERE ano = ? 
        ORDER BY data 
        LIMIT ?
        ''', (ano, limit))
        
        escalas = [dict(row) for row in cursor.fetchall()]
        
        # Formatar datas
        for escala in escalas:
            if escala.get('data'):
                data_obj = datetime.fromisoformat(escala['data'])
                escala['data_formatada'] = data_obj.strftime('%d/%m/%Y')
            
            if escala.get('data_trabalho_mensal'):
                data_trab = datetime.fromisoformat(escala['data_trabalho_mensal'])
                escala['trabalho_formatado'] = data_trab.strftime('%d/%m/%Y')
        
        conn.close()
        return escalas
    
    def obter_estatisticas(self):
        """Retorna estatísticas do sistema"""
        conn = get_db()
        cursor = conn.cursor()
        
        # Contar participantes
        cursor.execute('SELECT COUNT(*) as total FROM participantes WHERE ativo = 1')
        total_participantes = cursor.fetchone()['total']
        
        # Contar grupos
        cursor.execute('SELECT COUNT(*) as total FROM grupos_lar')
        total_grupos_lar = cursor.fetchone()['total']
        
        cursor.execute('SELECT COUNT(*) as total FROM grupos_tenda')
        total_grupos_tenda = cursor.fetchone()['total']
        
        # Contar escalas do ano atual
        ano = self.config['ano_vigente']
        cursor.execute('SELECT COUNT(*) as total FROM escalas_lar WHERE ano = ?', (ano,))
        total_defumacoes = cursor.fetchone()['total']
        
        cursor.execute('SELECT COUNT(*) as total FROM escalas_tenda WHERE ano = ?', (ano,))
        total_limpezas = cursor.fetchone()['total']
        
        conn.close()
        
        return {
            'ano': ano,
            'participantes': total_participantes,
            'grupos_lar': total_grupos_lar,
            'grupos_tenda': total_grupos_tenda,
            'defumacoes': total_defumacoes,
            'limpezas': total_limpezas
        }

# Inicializar sistema
sistema = SistemaEscalasWeb()

# ==================== ROTAS WEB ====================
@app.get("/", response_class=HTMLResponse)
async def pagina_login(request: Request):
    """Página de login com escolha de perfil"""
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/dashboard")
async def dashboard(
    request: Request, 
    username: str = "", 
    password: str = ""
):
    """Dashboard principal"""
    
    # Verificar quem é o usuário
    if username == ADMIN_USER and password == ADMIN_PASS:
        is_admin = True
        user_name = "Administrador"
    elif username == VIEWER_USER and password == VIEWER_PASS:
        is_admin = False
        user_name = "Visualizador"
    else:
        return RedirectResponse("/")  # Volta para login se credenciais inválidas
    
    # Obter dados (restrito para visualizadores)
    estatisticas = sistema.obter_estatisticas()
    
    if is_admin:
        escalas_lar = sistema.listar_escalas_lar(limit=10)
        escalas_tenda = sistema.listar_escalas_tenda(limit=10)
    else:
        escalas_lar = sistema.listar_escalas_lar(limit=5)
        escalas_tenda = sistema.listar_escalas_tenda(limit=5)
    
    context = {
        "request": request,
        "estatisticas": estatisticas,
        "escalas_lar": escalas_lar,
        "escalas_tenda": escalas_tenda,
        "is_admin": is_admin,          # IMPORTANTE!
        "user_name": user_name,        # IMPORTANTE!
    }
    
    return templates.TemplateResponse("dashboard.html", context)

# Rotas apenas para administradores
@app.get("/participantes", response_class=HTMLResponse)
async def participantes(
    request: Request, 
    credenciais: dict = Depends(verificar_admin)  # Só admin acessa
):
    """Página de participantes"""
    lista_participantes = sistema.listar_participantes()
    grupos_lar = sistema.listar_grupos_lar()
    grupos_tenda = sistema.listar_grupos_tenda()
    
    context = {
        "request": request,
        "participantes": lista_participantes,
        "grupos_lar": grupos_lar,
        "grupos_tenda": grupos_tenda,
        "is_admin": True,
        "user_name": "Administrador"
    }
    
    return templates.TemplateResponse("participantes.html", context)

@app.post("/participantes/adicionar")
async def adicionar_participante_post(
    request: Request,
    username: str = Form("admin"),
    password: str = Form("escala123"),
    nome: str = Form(...),
    telefone: str = Form(""),
    email: str = Form(""),
    instituicao: str = Form(...),
    grupo_lar: str = Form(""),
    grupo_tenda: str = Form("")
):
    """Rota POST para adicionar participante (manter compatibilidade)"""
    # Verificação básica de credenciais
    if username != ADMIN_USER or password != ADMIN_PASS:
        return RedirectResponse("/")
    
    # Prepara dados
    dados = {
        'nome': nome,
        'telefone': telefone,
        'email': email,
        'instituicao': instituicao,
        'grupo_lar': grupo_lar,
        'grupo_tenda': grupo_tenda
    }
    
    # Salva no banco
    try:
        sistema.adicionar_participante(dados)
        # Redireciona normalmente para manter compatibilidade
        return RedirectResponse(f"/participantes?username={username}&password={password}", status_code=303)
    except Exception as e:
        return HTMLResponse(
            content=f"<h1>Erro ao salvar: {str(e)}</h1>"
            "<a href='/participantes?username={username}&password={password}'>Voltar</a>",
            status_code=500
        )
    
@app.get("/participantes/adicionar")
async def adicionar_participante_get(
    username: str = "",
    password: str = "",
    nome: str = "",
    telefone: str = "",
    email: str = "",
    instituicao: str = "",
    grupo_lar: str = "",
    grupo_tenda: str = ""
):
    """Rota GET para compatibilidade (fallback)"""
    if username != ADMIN_USER or password != ADMIN_PASS:
        return RedirectResponse("/")
    
    # Se tem dados, salva
    if nome and instituicao:
        dados = {
            'nome': nome,
            'telefone': telefone,
            'email': email,
            'instituicao': instituicao,
            'grupo_lar': grupo_lar,
            'grupo_tenda': grupo_tenda
        }
        sistema.adicionar_participante(dados)
    
    # Redireciona de volta
    return RedirectResponse(f"/participantes?username={username}&password={password}")

@app.get("/participantes/excluir/{id}")
async def excluir_participante(id: int, username: str = "", password: str = ""):
    """Exclui participante"""
    if username != ADMIN_USER or password != ADMIN_PASS:
        return RedirectResponse("/")
    
    sistema.excluir_participante(id)
    return RedirectResponse(f"/participantes?username={username}&password={password}")

@app.get("/grupos", response_class=HTMLResponse)
async def grupos(
    request: Request, 
    credenciais: dict = Depends(verificar_admin)  # Só admin acessa
):
    """Página de grupos"""
    grupos_lar = sistema.listar_grupos_lar()
    grupos_tenda = sistema.listar_grupos_tenda()
    
    context = {
        "request": request,
        "grupos_lar": grupos_lar,
        "grupos_tenda": grupos_tenda,
        "is_admin": True,
        "user_name": "Administrador"
    }
    
    return templates.TemplateResponse("grupos.html", context)

@app.post("/grupos/adicionar/lar")
async def adicionar_grupo_lar(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    nome: str = Form(...),
    dia_defumacao: str = Form(...),
    ordem_rotacao: int = Form(1)
):
    """Adiciona grupo Lar"""
    if username != ADMIN_USER or password != ADMIN_PASS:
        return RedirectResponse("/")
    
    dados = {
        'nome': nome,
        'dia_defumacao': dia_defumacao,
        'ordem_rotacao': ordem_rotacao
    }
    
    sistema.adicionar_grupo_lar(dados)
    return RedirectResponse(f"/grupos?username={username}&password={password}")

@app.post("/grupos/adicionar/tenda")
async def adicionar_grupo_tenda(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    nome: str = Form(...),
    dia_preferencial: str = Form("")
):
    """Adiciona grupo Tenda"""
    if username != ADMIN_USER or password != ADMIN_PASS:
        return RedirectResponse("/")
    
    dados = {
        'nome': nome,
        'dia_preferencial': dia_preferencial
    }
    
    sistema.adicionar_grupo_tenda(dados)
    return RedirectResponse(f"/grupos?username={username}&password={password}")

# Rotas acessíveis por ambos (viewer e admin)
@app.get("/escalas", response_class=HTMLResponse)
async def escalas(
    request: Request, 
    credenciais: dict = Depends(qualquer_usuario)  # Ambos acessam
):
    """Página de escalas - acessível por todos"""
    escalas_lar = sistema.listar_escalas_lar()
    escalas_tenda = sistema.listar_escalas_tenda()
    
    context = {
        "request": request,
        "escalas_lar": escalas_lar,
        "escalas_tenda": escalas_tenda,
        "is_admin": credenciais["tipo"] == "admin",
        "user_name": "Administrador" if credenciais["tipo"] == "admin" else "Visualizador"
    }
    
    return templates.TemplateResponse("escalas.html", context)

@app.get("/gerar", response_class=HTMLResponse)
async def gerar_escala(
    request: Request, 
    credenciais: dict = Depends(verificar_admin)  # Só admin acessa
):
    """Página para gerar escala"""
    estatisticas = sistema.obter_estatisticas()
    
    context = {
        "request": request,
        "ano_atual": estatisticas['ano'],
        "is_admin": True,
        "user_name": "Administrador"
    }
    
    return templates.TemplateResponse("gerar.html", context)

@app.post("/api/gerar")
async def api_gerar_escala(
    ano: int = Form(...),
    credenciais: dict = Depends(verificar_admin)
):
    """API para gerar escala - apenas admin"""
    try:
        resultado = sistema.gerar_escala_anual(ano)
        return JSONResponse(resultado)
    except Exception as e:
        return JSONResponse({"sucesso": False, "erro": str(e)})

@app.post("/api/participantes")
async def api_adicionar_participante(
    request: Request,
    username: str = Form("admin"),
    password: str = Form("escala123"),
    nome: str = Form(...),
    telefone: str = Form(""),
    email: str = Form(""),
    instituicao: str = Form(...),
    grupo_lar: str = Form(""),
    grupo_tenda: str = Form("")
):
    """API para adicionar participante via AJAX"""
    if username != ADMIN_USER or password != ADMIN_PASS:
        return JSONResponse({"sucesso": False, "erro": "Credenciais inválidas"})
    
    try:
        dados = {
            'nome': nome,
            'telefone': telefone,
            'email': email,
            'instituicao': instituicao,
            'grupo_lar': grupo_lar,
            'grupo_tenda': grupo_tenda
        }
        
        participante_id = sistema.adicionar_participante(dados)
        return JSONResponse({"sucesso": True, "id": participante_id, "mensagem": "Participante adicionado com sucesso!"})
    except Exception as e:
        return JSONResponse({"sucesso": False, "erro": str(e)})

@app.post("/api/participantes/atualizar/{id}")
async def atualizar_participante_api(
    id: int,
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    nome: str = Form(...),
    telefone: str = Form(""),
    email: str = Form(""),
    instituicao: str = Form(...),
    grupo_lar: str = Form(""),
    grupo_tenda: str = Form(""),
    ativo: str = Form("1")
):
    """API para atualizar participante via AJAX"""
    if username != ADMIN_USER or password != ADMIN_PASS:
        return JSONResponse({"sucesso": False, "erro": "Credenciais inválidas"})
    
    try:
        dados = {
            'nome': nome,
            'telefone': telefone,
            'email': email,
            'instituicao': instituicao,
            'grupo_lar': grupo_lar,
            'grupo_tenda': grupo_tenda,
            'ativo': int(ativo)
        }
        
        sistema.atualizar_participante(id, dados)
        return JSONResponse({"sucesso": True, "mensagem": "Participante atualizado com sucesso!"})
    except Exception as e:
        return JSONResponse({"sucesso": False, "erro": str(e)})

@app.get("/exportar")
async def exportar_dados(credenciais: dict = Depends(verificar_admin)):
    """Exporta dados para Excel - apenas admin pode exportar"""
    try:
        # Coletar dados
        participantes = sistema.listar_participantes()
        grupos_lar = sistema.listar_grupos_lar()
        grupos_tenda = sistema.listar_grupos_tenda()
        escalas_lar = sistema.listar_escalas_lar()
        escalas_tenda = sistema.listar_escalas_tenda()
        
        # Criar Excel em memória
        from io import BytesIO
        import pandas as pd
        
        output = BytesIO()
        
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            pd.DataFrame(participantes).to_excel(writer, sheet_name='Participantes', index=False)
            pd.DataFrame(grupos_lar).to_excel(writer, sheet_name='Grupos Lar', index=False)
            pd.DataFrame(grupos_tenda).to_excel(writer, sheet_name='Grupos Tenda', index=False)
            pd.DataFrame(escalas_lar).to_excel(writer, sheet_name='Escala Lar', index=False)
            pd.DataFrame(escalas_tenda).to_excel(writer, sheet_name='Escala Tenda', index=False)
        
        output.seek(0)
        
        return Response(
            content=output.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=escalas.xlsx"}
        )
    except Exception as e:
        logger.error(f"Erro ao exportar dados: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"sucesso": False, "erro": f"Erro ao gerar arquivo Excel: {str(e)}"}
        )
    
# Adicione no seu main.py uma rota privada para backup
@app.get("/admin/backup")
async def fazer_backup(username: str = "", password: str = ""):
    if username != ADMIN_USER or password != ADMIN_PASS:
        return RedirectResponse("/")
    
    # Código do backup aqui
    return {"status": "backup criado"}

@app.get("/escalas/publica")
async def escalas_publicas(request: Request):
    # Versão pública sem dados sensíveis
    escalas = sistema.listar_escalas_lar()
    return templates.TemplateResponse("escalas_publica.html", {
        "request": request,
        "escalas": escalas,
        "is_admin": False,          # ← ADICIONAR (sempre False pois é pública)
        "user_name": "Visitante"    # ← ADICIONAR
    })

# ==================== TEMPLATES HTML ====================
# Criar diretório frontend se não existir
TEMPLATES_DIR.mkdir(exist_ok=True)
STATIC_DIR.mkdir(exist_ok=True)

# ==================== INICIALIZAR APLICAÇÃO ====================
if __name__ == "__main__":
    import uvicorn
    
    print("\n" + "="*60)
    print("SISTEMA DE ESCALAS WEB - PRONTO PARA HOSPEDAGEM")
    print("="*60)
    print("\n[INFO] Sistema inicializado com sucesso!")
    print(f"[INFO] Usuário padrão: {ADMIN_USER}")
    print(f"[INFO] Senha padrão: {ADMIN_PASS}")
    print(f"[INFO] Banco de dados: {DATA_DIR / 'escalas.db'}")
    
    print("\n[INICIANDO] Servidor local...")
    print("[URL] http://localhost:8000")
    print("\n[IMPORTANTE] Para hospedar na web:")
    print("1. Mude a senha em main.py (linha 59)")
    print("2. Escolha uma plataforma de hospedagem:")
    print("   • Render.com (recomendado)")
    print("   • Railway.app")
    print("   • PythonAnywhere")
    print("   • Vercel + Supabase")
    print("\nPressione Ctrl+C para parar\n")
    
    uvicorn.run("__main__:app", host="127.0.0.1", port=8000, reload=True)