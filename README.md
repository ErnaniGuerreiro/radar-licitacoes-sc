# Radar de Licitações · Santa Catarina

Painel que se atualiza sozinho a cada 2 horas, sem você fazer nada depois de configurar.

## Como funciona
1. O GitHub roda o `coletor.py` a cada 2 horas (de graça).
2. O coletor consulta o PNCP e o Farol TCE/SC (painel Oportunidades), junta os dois sem duplicar, compara com o histórico e mede a própria cobertura.
3. O site em `site/index.html` é publicado no GitHub Pages com os dados novos.
4. Você abre o endereço do painel e vê tudo atualizado.

## Configuração (uma vez só, ~15 minutos)
1. Crie uma conta em https://github.com (grátis).
2. Clique em **New repository**. Nome: `radar-licitacoes-sc`. Marque **Public** e crie.
   (Pages grátis exige repositório público. Os dados do PNCP já são públicos.)
3. Na página do repositório: **Add file → Upload files**. Arraste TODO o conteúdo desta pasta
   (arquivos `coletor.py`, `watchlist.json`, `README.md` e as pastas `site` e `.github`). Clique em **Commit changes**.
4. Vá em **Settings → Pages**. Em **Source**, escolha **GitHub Actions**.
5. Vá em **Actions → atualizar-painel → Run workflow**. No campo "dias", digite **45** e confirme.
   Espere terminar (de 10 a 40 minutos na primeira vez; as próximas são mais rápidas).
6. Abra `https://SEU-USUARIO.github.io/radar-licitacoes-sc/`. Pronto: é o seu painel.

## Radares e alertas
No painel, filtre o que lhe interessa e clique em **Salvar** em *Meus radares*. Para receber alertas no Telegram, abra *Usar nos alertas*, copie o texto e cole no arquivo `watchlist.json` do repositório. O alerta chega como **um resumo por radar**, nunca uma mensagem por licitação, e só a partir da segunda coleta.

## Alertas no Telegram (opcional)
Crie um bot com o @BotFather, pegue o token e o seu chat id. Em **Settings → Secrets and variables → Actions**
crie `TELEGRAM_TOKEN` e `TELEGRAM_CHAT_ID`. Edite `watchlist.json` com suas palavras-chave.

## Se algo der errado
Em **Actions**, clique na execução com ❌ e copie a mensagem de erro. A aba **Fontes e cobertura** do painel
mostra o que foi coletado por completo e o que falhou.
