# Epicure and open ingredient vocabularies: licence and provenance check

Date: 2026-11-09. Plan decision: D10 in `docs/plans/2026-11-05-m3-ingredient-foundation.md`.
Rule from D10: use a resource only if its licence AND its source provenance are both clear and compatible. If either is unclear, do not use it.

Labels: MEASURED means seen in a primary source. ESTIMATE means inferred from a secondary source. HYPOTHESIS means a guess.
No vocabulary data was downloaded or copied into the repo. Only page text was read.

## 1. What Epicure is

- Epicure is a research paper plus a small data bundle. It is not a published ontology or lexicon. (MEASURED)
- Title: "Epicure: Navigating the Emergent Geometry of Food Ingredient Embeddings".
- Authors: Jakub Radzikowski and Josef Chen. (MEASURED)
- arXiv 2605.22391 v1, submitted 21 May 2026. DOI 10.48550/arXiv.2605.22391. <https://arxiv.org/abs/2605.22391>
- The bundle holds three 300-dimension ingredient embeddings (Cooc, Chem, Core) over one vocabulary of 1,790 canonical ingredient names, plus `vocab.csv`. (MEASURED, ancillary `README.txt`)
- The bundle is an arXiv "ancillary file" list: `epicure_embeddings.tar.gz`, `epicure_supplementary_csvs.tar.gz`, `supplement.pdf`. <https://arxiv.org/src/2605.22391v1/anc>
- No GitHub, Zenodo or Hugging Face repository was found. (MEASURED on the abstract page)
- The vocabulary is a flat list of names with node ids. It holds no is_a edges and no UK/US synonym pairs. (ESTIMATE from the README description: "`vocab.csv` maps each ingredient name to its node ID in each model")

## 2. Epicure licence

- The paper is CC BY 4.0. The arXiv page says: "Creative Commons Attribution 4.0 (CC BY 4.0)". The PDF metadata says: `/License (http://creativecommons.org/licenses/by/4.0/)`. (MEASURED)
- This licence covers the paper. It does not say it covers the ancillary data. (HYPOTHESIS that it might)
- The ancillary bundle has no LICENSE or COPYING file. It has three README files, and none states a licence. (MEASURED: the file list at <https://arxiv.org/src/2605.22391v1/anc> and the two top-level README texts)
- arXiv says only: "Permission is granted through a license, chosen by the submitter." It does not say that the choice covers ancillary files. (MEASURED, <https://info.arxiv.org/help/license/index.html>)
- The abstract text on the HTML page says: "Code and trained artefacts are not released at this time." This conflicts with the ancillary bundle. The release status is unclear. (MEASURED)
- A secondary blog says "code and trained weights are not released yet". (ESTIMATE, <https://mer.vin/2026/05/epicure-food-ai-4-million-recipes-compressed-into-a-2mb-ingredient-map/>)
- Verdict on the licence: the data licence is UNCLEAR. A CC BY 4.0 paper licence would be compatible with MIT use if it applied, but nothing says it does.

## 3. Epicure provenance

- Corpus: 4,135,189 recipes from "11 publicly available datasets spanning seven languages". (MEASURED, <https://arxiv.org/html/2605.22391>, section 2.1)
- Largest sources: RecipeNLG 53.9%, XiaChuFang 37.4%, Povarenok 3.5%. The smaller ones are Vietnamese, Spanish, Turkish, Indian, Indonesian and German sets. (MEASURED, same section)
- RecipeNLG is the largest source. ADR 0003 bans RecipeNLG text, vocabulary and trained artefacts from the public app.
- Vocabulary method: about 200,000 raw ingredient strings, reduced to 1,790 by "an LLM-augmented canonicalisation pipeline" (Claude Opus family, Gemini Embedding clustering), then a manual pass. Non-English terms are machine-translated. (MEASURED, section 2.2)
- So the 1,790 names are canonical forms of strings taken from RecipeNLG, XiaChuFang and the other sets. The vocabulary is a derivative of those datasets. (ESTIMATE: the paper does not say how much of the vocabulary is shared with other sources)
- The paper gives no per-dataset licence and no ethics or data-availability section. (MEASURED)
- RecipeNLG terms allow non-commercial research and education. We found no public grant. (ADR 0003, MEASURED there)
- XiaChuFang and the other sets: licences not checked. They are scraped community recipes. (HYPOTHESIS)
- The paper also uses FlavorDB (compound graph) and USDA anchors. The FlavorDB licence was not checked. (UNVERIFIED)
- Whether a list of ingredient names is copyrightable is a legal question. This note is not legal advice. The project rule is stricter: "RecipeNLG ... vocabulary ... ship[s]" never. A list built from RecipeNLG strings is a RecipeNLG-derived vocabulary in spirit. Treat it as banned.

## 4. FoodOn (OBO Foundry)

What it is: a food ontology. Owner contact: Damion Dooley. Homepage <https://foodon.org/>. Release file `foodon.owl`, PURL <http://purl.obolibrary.org/obo/foodon.owl>. No version number was shown on the OBO page. (MEASURED, <https://obofoundry.org/ontology/foodon.html>)

Licence:
- OBO Foundry page: licence line "CC BY 4.0". (MEASURED)
- Repo README badge: "License: CC BY 4.0", and the repo has `LICENSE.txt` that starts "Attribution 4.0 International (CC BY 4.0)". (MEASURED, <https://github.com/FoodOntology/foodon>, `LICENSE.txt` raw)
- CC BY 4.0 allows reuse and adaptation with credit. It is compatible with shipping derived is_a edges in an MIT project, if the data file carries a credit and licence notice. It is not a ShareAlike licence. (ESTIMATE, from the standard CC BY 4.0 terms)

Provenance:
- README: "FoodOn was initially based on a conversion of the LanguaL.org food indexing thesaurus" and is "integrated with OBOFoundry ontology terms from UBERON, ChEBI, and NCBITaxon and others." (MEASURED)
- LanguaL licence: the LanguaL downloads page says the thesaurus "is provided to you free of charge". It names no licence. It also says texts and database "are protected by the European national laws". (MEASURED, <https://langual.org/langual_Downloads.asp>)
- So the part of FoodOn that came from LanguaL has an unclear upstream licence. The FoodOn CC BY 4.0 label does not prove that LanguaL permitted it. (HYPOTHESIS; the OBO page lists no caveat)
- FoodOn does not come from recipe corpora. The RecipeNLG risk does not apply. (ESTIMATE; the README does not list such sources)
- FoodOn is large (tens of MB OWL). Its classes use scientific and product-style labels, and many are not shopper names. (ESTIMATE, from `docs/RESEARCH_FINDINGS.md` and the OBO description "over 9,000 food products")

Verdict basis: the declared licence is clear and compatible. The upstream LanguaL status is unclear. The owner should accept the residual risk or reject it.

## 5. Other open resources

| Resource | Licence evidence | Gives | Status |
| --- | --- | --- | --- |
| Wikidata | "All structured data (i.e. the main, Property, Lexeme, and EntitySchema namespaces) is released into the public domain" (CC0). <https://www.wikidata.org/wiki/Wikidata:Licensing> (MEASURED) | `subclass of` (is_a) edges. English aliases ("also known as") that may include UK/US pairs | Clear. Aliases are uneven in quality. A query returns only what editors added. Record the item id and the retrieval date per edge |
| USDA FoodData Central | FDC homepage says data are public domain and published under "CC0 1.0 Universal". USDA asks for credit. (ESTIMATE: read through a search summary, the FAQ and download pages did not show the text) | Food names and category ids | Clear, but names are not shopper names. The project already uses it for the USDA id column |
| Open Food Facts ingredients taxonomy | Database: "available under the Open Database License (ODbL)". Contents: DbCL. <https://world.openfoodfacts.org/data> (MEASURED). The page says nothing about taxonomy files. (MEASURED) | Parents and multilingual synonyms in plain text | UNCLEAR for the taxonomy files. ODbL has a share-alike duty for derived databases. That could conflict with a plain MIT table. Do not use without an owner decision |
| Wikibooks Cookbook | CC BY-SA 4.0 (ADR 0003) | Names already in use | Already in the project |

Note on UK/US names: no source above has a ready UK/US list. Wikidata aliases are the best open candidate. A small hand list (courgette/zucchini, aubergine/eggplant, coriander/cilantro, rocket/arugula and so on) is clean by construction and is the safest source. (HYPOTHESIS)

## Verdicts

- **Epicure vocabulary (1,790 names, `vocab.csv`): DO NOT USE.** The data licence is unstated. The vocabulary derives from RecipeNLG (53.9% of its corpus) and other scraped sets with unchecked licences, which ADR 0003 forbids. Both D10 tests fail.
- **Epicure embeddings (Cooc, Chem, Core): DO NOT USE for shipping.** Same licence gap, trained on RecipeNLG-heavy data. Research-only use on Kaggle is a separate owner decision (HYPOTHESIS: allowed under RecipeNLG research terms).
- **FoodOn (is_a edges): USE AFTER OWNER CHECK.** The CC BY 4.0 licence is MEASURED and compatible. The upstream LanguaL licence is unclear. The owner decides whether that residual risk is acceptable. If yes, ship only the extracted edges with a credit line and a `LICENSES.md` entry. If no, use Wikidata only.
- **Wikidata (is_a edges and aliases): USE.** CC0 is MEASURED. Check each edge by hand, as ADR 0006 requires for any edge, and record the item id.
- **USDA FoodData Central (ids and category names): USE.** CC0 public domain, with credit. Licence text came from a search summary (ESTIMATE), so confirm it on the FDC site before release.
- **Open Food Facts ingredients taxonomy: USE AFTER OWNER CHECK.** Taxonomy-file licence not found. ODbL share-alike may not fit. Default is do not use.
