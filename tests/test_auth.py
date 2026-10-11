import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import func, select

from app import auth
from app.auth import NotAuthenticated, verify_token
from app.models import Statement
from tests.conftest import (
    SUPABASE_URL,
    USER_A,
    USER_B,
    client_for,
    make_token,
)

PDF = {"file": ("extrato.pdf", b"%PDF-1.4 conteudo qualquer", "application/pdf")}


# ---------- rotas protegidas ----------
def test_pagina_inicial_sem_login_redireciona(anon_client):
    response = anon_client.get("/")
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_upload_sem_login_e_recusado_e_nao_grava(anon_client, session):
    response = anon_client.post("/import", files=PDF)
    assert response.status_code == 303
    assert session.scalar(select(func.count()).select_from(Statement)) == 0


def test_docs_e_openapi_nao_ficam_expostos(anon_client):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert anon_client.get(path).status_code == 404


def test_pagina_de_login_e_publica(anon_client):
    assert anon_client.get("/login").status_code == 200


# ---------- validação do token ----------
def test_token_valido_identifica_o_usuario():
    user = verify_token(make_token(USER_A))
    assert (user.id, user.email) == (USER_A["sub"], "a@example.com")


@pytest.mark.parametrize(
    "token",
    [
        make_token(secret="outro-segredo-qualquer-com-32-bytes-ok!!"),  # assinatura forjada
        make_token(expires_in=-10),  # expirado
        make_token(aud="outro-publico"),  # audiência errada
        make_token(iss="https://evil.example.com/auth/v1"),  # emissor errado
        make_token(sub=None),  # sem sub
        make_token({"sub": "3" * 36, "email": "intruso@example.com"}),  # fora da allowlist
        "isto-nao-e-um-jwt",
    ],
)
def test_tokens_invalidos_sao_recusados(token):
    with pytest.raises(NotAuthenticated):
        verify_token(token)


def test_token_sem_assinatura_alg_none_e_recusado():
    import base64
    import json

    def b64(data):
        return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()

    header = b64({"alg": "none", "typ": "JWT"})
    payload = b64({**USER_A, "aud": "authenticated", "exp": 9999999999})
    forged = f"{header}.{payload}."
    with pytest.raises(NotAuthenticated):
        verify_token(forged)


def test_sem_allowlist_configurada_ninguem_entra(monkeypatch):
    monkeypatch.delenv("ALLOWED_EMAILS")
    with pytest.raises(NotAuthenticated):
        verify_token(make_token())


def test_hs256_nao_e_aceito_sem_segredo_configurado(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "")
    with pytest.raises(NotAuthenticated):
        verify_token(make_token())


def test_token_assimetrico_es256_via_jwks(monkeypatch):
    private = ec.generate_private_key(ec.SECP256R1())
    monkeypatch.setattr(auth, "_signing_key", lambda token, settings: private.public_key())
    token = make_token(secret=private, algorithm="ES256")
    assert verify_token(token).email == "a@example.com"
    # chave diferente da publicada => recusado
    other = ec.generate_private_key(ec.SECP256R1())
    with pytest.raises(NotAuthenticated):
        verify_token(make_token(secret=other, algorithm="ES256"))


def test_falha_ao_buscar_jwks_nao_vira_erro_500(monkeypatch):
    def boom(token, settings):
        raise httpx.ConnectError("sem rede")

    monkeypatch.setattr(auth, "_signing_key", boom)
    private = ec.generate_private_key(ec.SECP256R1())
    with pytest.raises(NotAuthenticated):
        verify_token(make_token(secret=private, algorithm="ES256"))


def test_cookie_com_token_invalido_redireciona_e_limpa(anon_client):
    anon_client.cookies.set("sb_access", make_token(expires_in=-5))
    response = anon_client.get("/")
    assert response.status_code == 303
    assert "sb_access" in response.headers["set-cookie"]


# ---------- login / logout ----------
def _fake_supabase(monkeypatch, status=200, body=None, error=None):
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        if error:
            raise error
        return httpx.Response(
            status, json=body if body is not None else {}, request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(auth.httpx, "post", fake_post)
    return calls


def test_login_correto_grava_cookie_seguro(anon_client, monkeypatch):
    calls = _fake_supabase(monkeypatch, body={"access_token": "tok-123", "expires_in": 1800})
    response = anon_client.post("/login", data={"email": "A@Example.com", "password": "x"})
    assert response.status_code == 303 and response.headers["location"] == "/"
    cookie = response.headers["set-cookie"].lower()
    assert "sb_access=tok-123" in cookie
    assert "httponly" in cookie and "secure" in cookie and "samesite=lax" in cookie
    assert "max-age=1800" in cookie
    url, kwargs = calls[0]
    assert url == f"{SUPABASE_URL}/auth/v1/token"
    assert kwargs["headers"]["apikey"] == "anon-key-de-teste"


def test_login_senha_errada_nao_grava_cookie(anon_client, monkeypatch):
    _fake_supabase(monkeypatch, status=400, body={"error": "invalid_grant"})
    response = anon_client.post("/login", data={"email": "a@example.com", "password": "errada"})
    assert response.status_code == 401
    assert "set-cookie" not in response.headers
    assert "inválidos" in response.text


def test_login_de_email_fora_da_allowlist_nem_consulta_o_supabase(anon_client, monkeypatch):
    calls = _fake_supabase(monkeypatch, body={"access_token": "t", "expires_in": 10})
    response = anon_client.post("/login", data={"email": "intruso@x.com", "password": "x"})
    assert response.status_code == 401
    assert calls == []
    assert "inválidos" in response.text  # mesma mensagem: não revela a allowlist


def test_login_com_supabase_fora_do_ar(anon_client, monkeypatch):
    _fake_supabase(monkeypatch, error=httpx.ConnectError("fora"))
    response = anon_client.post("/login", data={"email": "a@example.com", "password": "x"})
    assert response.status_code == 401


def test_login_sem_supabase_configurado_falha_fechado(anon_client, monkeypatch):
    monkeypatch.setenv("SUPABASE_ANON_KEY", "")
    response = anon_client.post("/login", data={"email": "a@example.com", "password": "x"})
    assert response.status_code == 401


def test_cookie_secure_pode_ser_desligado_so_para_localhost(anon_client, monkeypatch):
    monkeypatch.setenv("COOKIE_SECURE", "false")
    _fake_supabase(monkeypatch, body={"access_token": "t", "expires_in": 60})
    response = anon_client.post("/login", data={"email": "a@example.com", "password": "x"})
    assert "secure" not in response.headers["set-cookie"].lower()


def test_logout_limpa_o_cookie(client):
    response = client.post("/logout")
    assert response.status_code == 303 and response.headers["location"] == "/login"
    assert (
        'sb_access=""' in response.headers["set-cookie"]
        or "Max-Age=0" in response.headers["set-cookie"]
    )


# ---------- isolamento entre usuários ----------
def test_usuario_b_nao_ve_dados_do_usuario_a(client, session):
    client.post("/import", files=PDF)
    assert "FIIA11" in client.get("/").text

    client_b = client_for(session, USER_B)
    page_b = client_b.get("/")
    assert page_b.status_code == 200
    assert "FIIA11" not in page_b.text
    assert "Nenhum extrato importado" in page_b.text


def test_mesmo_arquivo_em_usuarios_diferentes_nao_conflita(client, session):
    assert client.post("/import", files=PDF).status_code == 200
    client_b = client_for(session, USER_B)
    assert client_b.post("/import", files=PDF).status_code == 200  # B não é "duplicado" de A
    owners = set(session.scalars(select(Statement.user_id)))
    assert owners == {USER_A["sub"], USER_B["sub"]}
    # e A continua barrado ao reimportar o próprio arquivo
    assert client.post("/import", files=PDF).status_code == 400
