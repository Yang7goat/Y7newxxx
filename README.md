# Vértice Logística & Varejo

Protótipo local de uma loja de tecnologia, feito com Python e SQLite, sem dependências externas.

## Executar

Requer Python 3.10 ou superior.

```powershell
python app.py
```

Abra `http://127.0.0.1:8000`. O banco `vertice.db` e o estoque inicial são criados automaticamente na primeira execução. Para rodar os testes:

```powershell
python -m unittest discover -s tests -v
```

O checkout depende de o processo `python app.py` permanecer aberto. Se o navegador mostrar uma falha de conexão, inicie o servidor no terminal e atualize a página.

## Publicar o backend no Render

O Netlify publica os arquivos estáticos, mas não executa este servidor Python. Para habilitar catálogo, estoque e pedidos no site publicado, publique este projeto também como um **Web Service** no Render e conecte o Netlify a ele. O servidor reconhece a variável `PORT` do Render e, em hospedagem, escuta no endereço público da instância; localmente continua usando `127.0.0.1:8000`.

1. Crie um repositório **privado** no GitHub e envie os arquivos do projeto, incluindo `app.py`, `integrations.py`, `app.js`, `styles.css`, `index.html` e a pasta `assets`. Não envie `vertice.db`, `.env` nem senhas. O `.gitignore` deste projeto já exclui esses arquivos locais.
2. No Render, crie um **Web Service** conectado a esse repositório, com `python app.py` como comando de início.
3. Configure um disco persistente no caminho `/var/data` e a variável `VERTICE_DATABASE=/var/data/vertice.db`. Sem o disco, o SQLite pode ser apagado quando a instância for substituída ou reiniciada.
4. Configure `VERTICE_FINANCE_PASSWORD` com uma senha forte e única. Mantenha `VERTICE_ALLOW_LIVE_PAYMENTS=no` e `VERTICE_WHATSAPP_SEND_ENABLED=false` até terminar a configuração e os testes dos provedores. Não use a senha local `1234` no serviço publicado.
5. Depois do deploy, teste `https://SEU-SERVICO.onrender.com/api/products`; deve retornar JSON contendo a lista de produtos. Guarde o domínio público do serviço.
6. Para ligar o frontend do Netlify à API, será necessário criar uma regra de proxy `/api/*` apontando para o domínio do Render e publicar novamente o site. O destino dessa regra só pode ser preenchido depois que o Render fornecer o domínio. As páginas de produto e acompanhamento também precisam de fallback para `/index.html` no Netlify.

Não publique o serviço antes de definir a senha forte da área empresarial. Este servidor de treino ainda precisa de endurecimento e configuração operacional antes de ser usado para vendas reais.

## O que está implementado

- Catálogo responsivo com fotos dos produtos, páginas de detalhe, preços e estoque.
- Carrossel de categorias com rolagem, filtros, seção de destaques e passos da compra.
- Carrinho persistido no navegador e checkout de demonstração com Pix, cartão e boleto.
- Registro local de pedidos e página de acompanhamento após confirmar.
- Integrações preparadas para Mercado Pago Checkout Pro e WhatsApp Cloud API; sem credenciais, a loja permanece em demonstração.
- Links de WhatsApp para envio manual no modo de demonstração e mensagens oficiais automáticas quando habilitadas e configuradas.
- Reserva de estoque e gravação do pedido na mesma transação SQLite. Pedidos simultâneos não conseguem vender a mesma unidade.
- Área financeira protegida por senha, com receita, custo e lucro bruto **hipotéticos** por produto.

## Preparar integrações de teste

O modo padrão continua sendo demonstração. Para iniciar o Mercado Pago Checkout Pro em modo de teste, configure as credenciais de teste da sua aplicação localmente. **Não use token de produção neste computador compartilhado e nunca cole tokens no código ou na conversa.**

```powershell
$env:VERTICE_MERCADOPAGO_MODE = "test"
$env:VERTICE_MERCADOPAGO_ACCESS_TOKEN = "TEST-seu-token-local"
$env:VERTICE_PUBLIC_BASE_URL = "https://seu-tunel-https.example"
$env:VERTICE_MERCADOPAGO_WEBHOOK_SECRET = "segredo-configurado-no-painel"
python app.py
```

O `VERTICE_PUBLIC_BASE_URL` precisa apontar para um túnel HTTPS público que encaminhe à porta local `8000`. Configure no painel de desenvolvedor do Mercado Pago a URL `$env:VERTICE_PUBLIC_BASE_URL/api/webhooks/mercadopago`, selecione notificações de pagamentos e use o segredo de assinatura fornecido pelo Mercado Pago em `VERTICE_MERCADOPAGO_WEBHOOK_SECRET`. O checkout fica bloqueado até que a URL pública e o segredo do webhook estejam configurados, para evitar pedidos reais sem confirmação confiável. As credenciais de teste e um comprador de teste precisam pertencer ao mesmo ambiente de teste. Sem túnel, a integração permanece indisponível e a demonstração local continua funcionando.

O Checkout Pro hospeda a tela de pagamento do Mercado Pago e evita que este site receba dados de cartão. Ele apresenta os métodos disponíveis para a conta (como Pix, cartão ou boleto). O estado “Pagamento confirmado” só é gravado depois que o servidor consulta o pagamento no Mercado Pago e confere pedido, status, valor e moeda.

### WhatsApp Cloud API

Crie no WhatsApp Manager e aguarde a aprovação de dois **modelos utilitários** em português brasileiro. O modelo do cliente precisa aceitar quatro variáveis no corpo, na ordem: código do pedido, status, total e forma de pagamento. O modelo do armazém precisa aceitar seis: código, nome do cliente, produtos, total, forma de pagamento e status. Os nomes aprovados vão em `VERTICE_WHATSAPP_CUSTOMER_TEMPLATE` e `VERTICE_WHATSAPP_SELLER_TEMPLATE`.

Configure localmente `VERTICE_WHATSAPP_ACCESS_TOKEN`, `VERTICE_WHATSAPP_PHONE_NUMBER_ID` e os nomes dos modelos aprovados antes de iniciar o servidor. O cliente só recebe mensagens automáticas se marcar o consentimento no checkout; o armazém recebe avisos de pedido pendente e, após confirmação, de pagamento aprovado. Nunca separe ou envie mercadoria apenas com base no pedido pendente.

O envio fica desligado por padrão. Para habilitá-lo explicitamente após validar os modelos e destinatários, configure `VERTICE_WHATSAPP_SEND_ENABLED=true`. Em ambiente de teste, use os destinatários de teste aceitos pela Meta; não habilite o envio para números reais sem consentimento e validação.

Exemplo de corpos compatíveis com as variáveis enviadas:

```text
Cliente: Pedido {{1}} na Vértice: {{2}}. Total {{3}}. Pagamento: {{4}}.
Armazém: Pedido {{1}}. Cliente {{2}}. Produtos: {{3}}. Total {{4}}. Pagamento: {{5}}. Status: {{6}}. Aguarde confirmação antes de separar.
```

O arquivo `.env.example` lista os nomes das variáveis; mantenha valores secretos somente no ambiente local.

Para habilitar a área financeira, configure uma senha antes de iniciar o servidor:

```powershell
$env:VERTICE_FINANCE_PASSWORD = "defina-uma-senha-local"
python app.py
```

## Limites desta demonstração

Sem credenciais, a loja continua no modo de pedidos fictícios. Pagamentos reais ficam bloqueados por padrão: `VERTICE_ALLOW_LIVE_PAYMENTS=yes` só deve ser configurado após implantação pública e validação completa. A ativação requer conta Mercado Pago, credenciais separadas de teste/produção, URL HTTPS pública e segredo de webhook; e, para mensagens, WhatsApp Business configurado, modelos utilitários aprovados, envio habilitado e consentimento do cliente. Esta implementação ainda precisa de testes na conta real, proteção operacional contra pedidos pendentes expirados e implantação/monitoramento antes do uso em produção. Os dados financeiros e custos por produto continuam hipotéticos; o relatório exclui pedidos ainda não pagos. Não exponha este servidor na internet sem completar essas etapas.
