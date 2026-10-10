# nyt_news_collector

Coleta diária de artigos do New York Times (via API oficial do NYT), com envio de um e-mail-resumo (CSV) e gravação no mesmo banco Oracle usado pelo projeto Google Alerts. Migrado de um script local (Task Scheduler do Windows) para um serviço em servidor (Easypanel + n8n).

## Visão geral do pipeline

NYT API → serviço HTTP (Easypanel) → Oracle Autonomous Database (NYT_OWNER.NYT_ARTICLE) → e-mail diário (CSV)
Disparo: workflow agendado no n8n (20:00 ET, diário)

- **`oracle_collector/` (Fase 1)**: busca os artigos do dia e grava no Oracle, sem e-mail. Hoje só ferramenta manual (agendamento desativado por redundância com a Fase 2).
- **`email_collector/` (Fase 2, em produção)**: pipeline real — busca, grava no Oracle, e manda o e-mail-resumo. Substituiu o agendamento local no Windows.

## O que já foi construído

- Migração de um script local (dependente do notebook ligado + Task Scheduler do Windows) pra um serviço containerizado, hospedado em VPS, orquestrado pelo n8n.
- Armazenamento unificado: artigos do NYT no mesmo banco Oracle do projeto Google Alerts, schema isolado (`NYT_OWNER`) — evita manter dois bancos separados.
- Backfill do histórico: ~79 mil artigos migrados do banco local (MySQL) pro Oracle, validados ponta a ponta.
- Identificada e corrigida uma divergência entre o código documentado no repositório e o que de fato rodava em produção (o script real era diferente do protótipo que estava no repo) — a migração partiu do script realmente em uso.
- Infraestrutura antiga desligada: tarefa do Task Scheduler do Windows e servidor local desativados após a migração.

## Problemas encontrados e resolvidos (histórico)

- **Divergência entre código documentado e código real em produção**: identificada antes de migrar o processo errado.
- **Permissões do Oracle**: o usuário de aplicação precisou de concessões adicionais (`CREATE SESSION`, cota de tablespace) na configuração inicial — resolvidas.
- **Wallet do Oracle em contêiner**: exige o wallet extraído, não só referenciado como `.zip` — resolvido com o wallet em base64 na variável de ambiente de produção.
- **Segurança — segredos no código**: numa fase anterior, chaves de API e credenciais de SMTP chegaram a ficar commitadas em texto puro. O código atual foi refatorado para ler segredos só de variáveis de ambiente, e o histórico do branch principal foi reescrito para remover esses valores dos arquivos rastreados.
- **Risco de envio duplicado**: o desligamento do agendamento antigo foi feito no mesmo momento da ativação do novo workflow, evitando duplicar o e-mail.

## Infraestrutura

- Hospedado numa VPS (Hostinger) com Easypanel, mesma instância do n8n do projeto Google Alerts.
- Orquestração via workflow agendado no n8n, diário.
- Dado não depende da VPS: armazenamento na Oracle Autonomous Database (OCI), serviço separado.

## Limitações conhecidas

- Mesmo banco Oracle do projeto Google Alerts — sujeito ao mesmo teto de 20GB do tier Always Free.
- Código legado (um protótipo FastAPI+MySQL nunca usado em produção) ainda presente no repositório, aguardando remoção.

## Projetos relacionados

- [`google-alerts-parser`](https://github.com/hernanijorge/google-alerts-parser) — coleta e parsing de alertas do Google, mesmo banco Oracle (schema separado).
