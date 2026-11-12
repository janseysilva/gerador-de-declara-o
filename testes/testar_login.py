# -*- coding: utf-8 -*-
"""
Abre o programa com o login ligado a uma ponte de MENTIRA (Node, só neste computador), para dar para testar
a tela de entrada, os perfis e a tela de Usuários sem usar o Google. As contas de teste são recriadas a cada
abertura e ficam listadas no arquivo "Contas de teste do login.txt" (na Área de Trabalho).

    python testes/testar_login.py            (o atalho Testar_Login.bat faz isso)
"""
import os
import subprocess
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, ".."))
sys.path.insert(0, AQUI)
import acesso  # noqa: E402
import teste_acesso as ta  # noqa: E402

CONTAS = (
    ("Administrador de Teste", "admin@exemplo.com", "Firme-Teste-9", ["admin"]),
    ("Ana (só Declarações)", "ana@exemplo.com", "Boa-Senha-77", ["declaracoes"]),
    ("Beto (só Estoque)", "beto@exemplo.com", "Boa-Senha-77", ["estoque"]),
    ("Carla (Declarações e Estoque)", "carla@exemplo.com", "Boa-Senha-77", ["declaracoes", "estoque"]),
)


def preparar_contas(ponte):
    prov = ponte.senha_provisoria_de(ta.ADMIN)
    s, erro = acesso.entrar(ta.ADMIN, prov)
    assert s, erro
    ok, texto = acesso.alterar_senha(ta.ADMIN, prov, CONTAS[0][2])
    assert ok, texto
    admin, erro = acesso.entrar(ta.ADMIN, CONTAS[0][2])
    assert admin, erro
    for nome, email, senha, perfis in CONTAS[1:]:
        assert acesso.cadastrar(nome, email, senha)[0]
        assert acesso.atualizar(admin, email, perfis=perfis, status="autorizado", validade="")[0]
    assert acesso.cadastrar("Davi (aguardando liberação)", "davi@exemplo.com", "Boa-Senha-77")[0]   # fica pendente
    return admin


def escrever_lista(caminho):
    linhas = ["CONTAS DE TESTE DO LOGIN (valem só enquanto o programa de teste estiver aberto)", "",
              "Nada daqui é de verdade: o servidor é de mentira e é apagado quando você fecha o programa.", ""]
    for nome, email, senha, perfis in CONTAS:
        linhas.append("{}\n    e-mail: {}\n    senha:  {}\n".format(nome, email, senha))
    linhas.append("Davi (aguardando liberação)\n    e-mail: davi@exemplo.com\n    senha:  Boa-Senha-77\n"
                  "    (entre como administrador, abra “Usuários” e libere o Davi com os perfis que quiser)\n")
    with open(caminho, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas))


def main():
    destino = os.path.join(os.path.expanduser("~"), "Desktop", "Contas de teste do login.txt")
    with ta.Ponte(isolar=False) as ponte:            # fica com a pasta de dados que o atalho escolheu
        preparar_contas(ponte)
        escrever_lista(destino)
        import declaracoes_escolares as de
        de.main()


if __name__ == "__main__":
    main()
