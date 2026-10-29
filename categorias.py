"""
Classificador de objetos de licitação por categoria.
Ignora acentos e maiúsculas (muitos objetos vêm como "AQUISICAO", sem acento).
Cada categoria tem padrões; vence a que casar mais padrões distintos (empate: ordem da lista).
"""
import re
import unicodedata

REGRAS = [
    ("Saúde", r"medicament|hospital|ambulanc|saude|odontolog|laborator|clinic|exames?\b|cirurg|enferm|raio.?x|ultrassom|hemodi|fisioterap|psicolog|fonoaudi|terapeut|vacina|oxigenio|ortese|protese|consultas?\b|medic|farmac|urgencia|hemoterap|diagnost|tomograf|ressonanc|\bsus\b|\bubs\b|material penso|insumos hospitalar|raios? x|dialise|oftalm|ortoped|cardio|anestes"),
    ("Obras e engenharia", r"\bobras?\b|pavimenta|construcao|reforma|drenagem|asfalt|\bpontes?\b|engenharia|edificac|terraplan|calcament|ampliacao|galpao|\bpraca\b|\bquadra\b|\bmuro\b|contencao|bueiro|meio.?fio|paisagism|projeto executivo|recapeamento|demolicao|empreitada|execucao de .{0,40}(obra|servicos de engenharia)|\bcei\b|escola|unidade basica|passeio|ciclovia|cobertura de|banheiros? publicos|pintura de"),
    ("Materiais de construção e ferramentas", r"material de construcao|materiais? (hidraulic|eletric|de construcao)|cimento|tubos?\b|\bbrita\b|agregado|\bareia\b|\bpedra\b|madeira|ferragens|\btintas?\b|ferramentas|concreto|britad|rachao|blocos?\b|tijolo|vergalh|eletroduto|cabos? eletric|argamassa|pre.?moldad|manilha|saibro|cascalho|rejeito"),
    ("Tecnologia da informação e telecom", r"software|sistema (de gestao|informatizado|integrado)|informatic|computador|notebook|tecnologia da informacao|licenca de uso|\binternet\b|servidor(es)? de|impressora|rede de dados|telefonia|telecomunic|cabeamento|wi.?fi|cameras?|videomonitoramento|\bnuvem\b|hospedagem de (sistema|site)|\bti\b|tablets?|monitor(es)? de video|link de dados|\bsite\b|aplicativo|digitalizacao|certificado digital"),
    ("Alimentação e merenda", r"merenda|generos alimenticios|alimentacao escolar|refeic|hortifrut|\bcarnes?\b|\bpao\b|paes\b|alimentos?\b|cesta basica|frango|\bleite\b|marmit|lanche|coffee|agua mineral|bebidas?|\bovos\b|hortalic|panificac|gas de cozinha|gas glp|alimentacao|nutricao|dieta"),
    ("Veículos, máquinas e combustíveis", r"veiculo|combustive|diesel|gasolina|etanol|pneus?\b|caminh|onibus|maquinas?\b|tratores?\b|retroescavadeira|motoniveladora|escavadeira|automovel|automotiv|lubrificante|\boleo|oficina mecanica|cacamba|pa carregadeira|rolo compactador|implementos?|micro.?onibus|van\b|motocicleta|pecas (e acessorios|para)|rodoviari|frota|abastecimento de veiculo"),
    ("Educação", r"escolar|educacao|didatico|transporte escolar|creche|ensino|alunos?\b|\bescolas?\b|professor|biblioteca|\blivros?\b|pedagog|educacional|\bcmei\b|educandos|alfabetiza|infantil|estudantes?"),
    ("Limpeza, resíduos e conservação", r"limpeza|conservacao|coleta (de|e) (lixo|residuos)|residuos|capina|rocada|jardinagem|higieniza|dedetiza|desinsetiza|desratiza|aterro|reciclagem|varricao|sanitiza|banheiros? quimic|\bpoda\b|lixo|conservacao de vias|material de limpeza|sacos? de lixo"),
    ("Serviços profissionais e consultoria", r"assessoria|consultoria|servicos? tecnicos?|advocaticio|contabil|treinamento|capacitacao|auditoria|pericia|avaliacao tecnica|laudos?\b|georreferenc|topograf|agrimensura|palestr|\bcursos?\b|juridic|concurso publico|selecao publica|avaliacao de imove|projeto basico|elaboracao de projeto|plano (diretor|municipal)|fiscalizacao tecnica|gerenciamento|supervisao"),
    ("Material de escritório", r"papelaria|material de expediente|escritorio|\btoner|cartucho|\bpapel\b|resma|carimbo|material de consumo|suprimentos de informatica|envelope|pastas?\b|caneta"),
    ("Eventos, cultura e esporte", r"\beventos?\b|\bshows?\b|bandas?\b|artistas?\b|apresentac|musical|cultural|festival|natal\b|natalin|pirotecn|sonorizacao|palco|iluminacao cenica|carnaval|\bfestas?\b|esport|ginasio|campeonato|instrumentos? musica|decorac|premiacao|trofeu|medalha|cultura\b|teatro|oficinas|folclor|\bfeira\b|exposicao|rodeio|tradicion|desfile|banda marcial|torneio|corrida"),
    ("Assistência social e acolhimento", r"acolhimento|assistencia social|\bidos[oa]s?\b|\bilpi\b|longa permanencia|abrigo|\bcras\b|\bcreas\b|funerari|funeral|cremacao|sepultamento|vulnerabilidade|conselho tutelar|socioeducativ|residencia terapeutica|beneficio eventual|\burnas?\b|cadunico|servico de convivencia|passe livre"),
    ("Agropecuária e meio ambiente", r"agricol|agropecuari|sementes?\b|\bmudas?\b|silagem|gradagem|adubo|fertilizante|calcario|pecuari|veterinari|\banimais\b|\bracao\b|apicultura|piscicultura|reflorest|ambiental|patrulha agricola|irrigacao|inseminacao|calagem|corretivo de solo|insumos agricolas|bovin|suino|agricultor|produtor rural|horta"),
    ("Energia e iluminação pública", r"iluminacao publica|\benergia\b|luminaria|\bled\b|lampadas?\b|eletrific|subestacao|fotovoltaic|\bsolar\b|\bpostes?\b|rede de distribuicao|gerador|energia eletrica|reator|relé|transformador"),
    ("Segurança e proteção", r"seguranca|vigilancia|\bepis?\b|equipamentos? de protecao|uniforme|fardamento|extintor|bombeiro|alarme|monitoramento|\bguarda\b|armamento|seguranca do trabalho|colete|bota\b|botas\b|luvas|capacete|sinalizacao|defesa civil"),
    ("Locação, hospedagem e viagens", r"locacao|aluguel|hospedagem|passagens?\b|viagens?\b|translado|diarias|agenciamento|estrutur(a|as) (para|de) (evento|palco|tenda)|tendas?\b|banheiros? quimic"),
    ("Alienação e leilão de bens", r"alienacao|leilao|bens moveis inserv|bens inserv|desfazimento|sucatas?\b|venda de|concessao (de uso|onerosa)|permissao de uso|cessao|outorga|arrendamento|bens imoveis|imovel"),
    ("Manutenção e serviços gerais", r"manutencao|conserto|reparos?\b|instalacao|montagem|servicos gerais|apoio administrativo|mao.?de.?obra|terceiriza|servente|pedreiro|encanador|eletricista|operador de|zeladoria|recepcao|telefonista|copeira|motorista|jardineiro|auxiliar de|vigia|lavanderia|reprografia"),
    ("Mobiliário e equipamentos", r"mobiliario|\bmoveis\b|cadeiras?\b|\bmesas?\b|armario|ar.?condicionado|eletrodomestic|equipamentos?\b|bebedouro|geladeira|refrigerador|climatiza|playground|brinquedo|fogao|freezer|micro.?ondas|ventilador|colchao|estante|arquivo de aco|aparelhos?\b|bens permanentes"),
    ("Saneamento e água", r"\bagua\b|esgoto|saneamento|hidrometro|tratamento de agua|hipoclorito|cloreto|reservatorio|\bpocos?\b|adutora|abastecimento de agua|estacao de tratamento|\bcloro\b|\bete\b|\beta\b|encanamento|caixa d.?agua|pvc"),
    ("Serviços financeiros e seguros", r"instituicao(oes)? financeira|folha de pagamento|\bseguros?\b|\bbanco\b|credito consignado|corretagem|previdenc|arrecadacao|tributos|cobranca"),
    ("Publicidade e comunicação", r"publicidade|propaganda|divulgacao|\bmidia\b|radiodifusao|\bradio\b|\bjornal\b|comunicacao|assessoria de imprensa|grafica|banner|comunicacao visual|impressos|placas|outdoor|faixas|camiseta|brindes?"),
]
_COMPILADAS = [(nome, re.compile(padrao)) for nome, padrao in REGRAS]


def normalizar(texto):
    t = unicodedata.normalize("NFD", texto or "")
    return "".join(c for c in t if unicodedata.category(c) != "Mn").lower()


def classificar(objeto):
    t = normalizar(objeto)
    melhor, pontos = "Outros", 0
    for nome, rx in _COMPILADAS:
        n = len(set(rx.findall(t)))
        if n > pontos:
            melhor, pontos = nome, n
    return melhor


CATEGORIAS = [n for n, _ in REGRAS] + ["Outros"]
