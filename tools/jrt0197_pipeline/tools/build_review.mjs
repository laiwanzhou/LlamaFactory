// Copyright 2025 HuggingFace Inc. and the LlamaFactory team.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";
import JSZip from "jszip";

const SHEETS = ["审核说明", "候选规则", "自动校验问题", "差异对照", "统计汇总", "候选清单"];
const PREVIEW_NAMES = ["01-instructions", "02-candidates", "03-validation", "04-diff", "05-statistics", "06-checklist"];

function argumentsOf(argv) {
  const result = {};
  for (let index = 0; index < argv.length; index += 2) result[argv[index].replace(/^--/, "")] = argv[index + 1];
  return result;
}

function columnName(index) {
  let value = index + 1;
  let result = "";
  while (value > 0) {
    value -= 1;
    result = String.fromCharCode(65 + (value % 26)) + result;
    value = Math.floor(value / 26);
  }
  return result;
}

function applyTableStyle(sheet, headers, rowCount, editable, tableName) {
  const last = columnName(headers.length - 1);
  const used = sheet.getRange(`A1:${last}${Math.max(2, rowCount + 1)}`);
  used.format = { wrapText: true, verticalAlignment: "top", borders: { preset: "all", style: "thin", color: "#D9E2F3" } };
  sheet.getRange(`A1:${last}1`).format = { fill: "#1F4E78", font: { bold: true, color: "#FFFFFF" }, wrapText: true };
  sheet.freezePanes.freezeRows(1);
  if (rowCount > 0) sheet.tables.add(`A1:${last}${rowCount + 1}`, true, tableName);
  headers.forEach((header, index) => {
    const column = sheet.getRange(`${columnName(index)}1:${columnName(index)}${Math.max(2, rowCount + 1)}`);
    column.format.columnWidth = ["class2_definition", "class3_definition", "class4_description", "raw_extraction", "normalized_content", "inheritance_trace"].includes(header) ? 34 : 18;
    if (editable.has(header) && rowCount > 0) sheet.getRange(`${columnName(index)}2:${columnName(index)}${rowCount + 1}`).format.fill = "#FFF2CC";
  });
}

function writeObjects(sheet, rows, editable = new Set(), tableName = "ReviewTable") {
  const headers = rows.length ? Object.keys(rows[0]) : ["状态"];
  const values = [headers, ...(rows.length ? rows.map((row) => headers.map((header) => row[header] ?? "")) : [["无记录"]])];
  sheet.getRangeByIndexes(0, 0, values.length, headers.length).values = values;
  applyTableStyle(sheet, headers, rows.length, editable, tableName);
}

function writeKeyValues(sheet, value, tableName) {
  const rows = Object.entries(value).map(([key, item]) => ({ 项目: key, 值: typeof item === "object" ? JSON.stringify(item) : item }));
  writeObjects(sheet, rows, new Set(), tableName);
}

async function canonicalizeRelationshipIds(zip, relationshipsPath, ownerPath) {
  const relationshipFile = zip.file(relationshipsPath);
  if (!relationshipFile) return;
  let relationshipsXml = await relationshipFile.async("string");
  let ownerXml = ownerPath ? await zip.file(ownerPath).async("string") : null;
  const ids = [...relationshipsXml.matchAll(/<(?:[A-Za-z]+:)?Relationship\b[^>]*\bId="([^"]+)"[^>]*\/>/g)].map((match) => match[1]);
  ids.forEach((oldId, index) => {
    const newId = `rId${index + 1}`;
    relationshipsXml = relationshipsXml.replaceAll(`Id="${oldId}"`, `Id="${newId}"`);
    if (ownerXml !== null) ownerXml = ownerXml.replaceAll(`r:id="${oldId}"`, `r:id="${newId}"`);
  });
  zip.file(relationshipsPath, relationshipsXml, { date: new Date("1980-01-01T00:00:00Z") });
  if (ownerXml !== null) zip.file(ownerPath, ownerXml, { date: new Date("1980-01-01T00:00:00Z") });
}

async function main() {
  const args = argumentsOf(process.argv.slice(2));
  if (!args.contract || !args.workbook || !args["preview-dir"]) throw new Error("--contract, --workbook, and --preview-dir are required");
  const contract = JSON.parse(await fs.readFile(args.contract, "utf8"));
  const workbook = Workbook.create();
  const sheets = Object.fromEntries(SHEETS.map((name) => [name, workbook.worksheets.add(name)]));
  const diagnostic = contract.diagnostic_only ? "是（存在阻断错误，不可冻结）" : "否";
  writeKeyValues(sheets["审核说明"], {
    标准: "JR/T 0197—2020 表A.1",
    运行ID: contract.run_id,
    诊断模式: diagnostic,
    使用说明: "黄色列为人工审核/修改建议列；工作簿不是真值载体，冻结由Python重新校验。",
  }, "InstructionsTable");
  writeObjects(sheets["候选规则"], contract.records, new Set(contract.editable_columns), "CandidatesTable");
  writeObjects(sheets["自动校验问题"], contract.findings, new Set(), "FindingsTable");
  writeKeyValues(sheets["差异对照"], contract.diff, "DiffTable");
  writeKeyValues(sheets["统计汇总"], contract.statistics, "StatisticsTable");
  writeObjects(sheets["候选清单"], contract.records.map((row) => ({ candidate_id: row.candidate_id, source_order: row.source_order, physical_page: row.source_physical_page, class1: row.class1, class2: row.class2, class3: row.class3, class4: row.class4, minimum_security_level: row.minimum_security_level, validation_flags: row.validation_flags })), new Set(), "ChecklistTable");

  const metadata = workbook.worksheets.add("__review_metadata");
  writeKeyValues(metadata, contract.metadata, "MetadataTable");
  metadata.visibility = "hidden";
  metadata.protection = { sheet: true, objects: true, scenarios: true };

  await fs.mkdir(args["preview-dir"], { recursive: true });
  for (let index = 0; index < SHEETS.length; index += 1) {
    const sheet = sheets[SHEETS[index]];
    const used = sheet.getUsedRange();
    const range = index === 1 ? "A1:AB20" : index === 5 ? "A1:I30" : used.address;
    const preview = await workbook.render({ sheetName: SHEETS[index], range, scale: 1, format: "png" });
    await fs.writeFile(path.join(args["preview-dir"], `${PREVIEW_NAMES[index]}.png`), new Uint8Array(await preview.arrayBuffer()));
  }
  const output = await SpreadsheetFile.exportXlsx(workbook);
  const artifactToolOutput = `${args.workbook}.artifact-tool.tmp.xlsx`;
  await output.save(artifactToolOutput);
  const zip = await JSZip.loadAsync(await fs.readFile(artifactToolOutput));
  const workbookXmlPath = "xl/workbook.xml";
  let workbookXml = await zip.file(workbookXmlPath).async("string");
  const sheetMatch = workbookXml.match(/<(?:[A-Za-z]+:)?sheet\b[^>]*name="__review_metadata"[^>]*\/>/);
  if (!sheetMatch) throw new Error("metadata sheet is absent from exported workbook XML");
  const relationshipMatch = sheetMatch[0].match(/r:id="([^"]+)"/);
  if (!relationshipMatch) throw new Error("metadata sheet relationship is absent");
  workbookXml = workbookXml.replace(sheetMatch[0], sheetMatch[0].replace("/>", ' state="hidden"/>'));
  zip.file(workbookXmlPath, workbookXml, { date: new Date("1980-01-01T00:00:00Z") });

  const relationships = await zip.file("xl/_rels/workbook.xml.rels").async("string");
  const relationship = relationships.match(new RegExp(`<(?:[A-Za-z]+:)?Relationship\\b[^>]*Id="${relationshipMatch[1]}"[^>]*/>`));
  if (!relationship) throw new Error("metadata worksheet relationship cannot be resolved");
  const target = relationship[0].match(/Target="([^"]+)"/)[1].replace(/^\//, "");
  const worksheetPath = target.startsWith("xl/") ? target : `xl/${target}`;
  let worksheetXml = await zip.file(worksheetPath).async("string");
  worksheetXml = worksheetXml.replace(
    /<([A-Za-z]+:)?sheetData>/,
    (match, prefix = "") => `<${prefix}sheetProtection sheet="1" objects="1" scenarios="1"/>${match}`,
  );
  zip.file(worksheetPath, worksheetXml, { date: new Date("1980-01-01T00:00:00Z") });

  for (const sheetName of SHEETS) {
    const escapedName = sheetName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const userSheet = workbookXml.match(new RegExp(`<(?:[A-Za-z]+:)?sheet\\b[^>]*name="${escapedName}"[^>]*/>`));
    if (!userSheet) throw new Error(`worksheet ${sheetName} is absent from workbook XML`);
    const userRelationshipId = userSheet[0].match(/r:id="([^"]+)"/)[1];
    const userRelationship = relationships.match(new RegExp(`<(?:[A-Za-z]+:)?Relationship\\b[^>]*Id="${userRelationshipId}"[^>]*/>`));
    const userTarget = userRelationship[0].match(/Target="([^"]+)"/)[1].replace(/^\//, "");
    const userPath = userTarget.startsWith("xl/") ? userTarget : `xl/${userTarget}`;
    let userXml = await zip.file(userPath).async("string");
    userXml = userXml.replace(
      /<([A-Za-z]+:)?sheetFormatPr\b/,
      (match, prefix = "") => `<${prefix}sheetViews><${prefix}sheetView workbookViewId="0"><${prefix}pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></${prefix}sheetView></${prefix}sheetViews>${match}`,
    );
    zip.file(userPath, userXml, { date: new Date("1980-01-01T00:00:00Z") });
  }
  await canonicalizeRelationshipIds(zip, "_rels/.rels", null);
  await canonicalizeRelationshipIds(zip, "xl/_rels/workbook.xml.rels", "xl/workbook.xml");
  for (let index = 1; index <= SHEETS.length + 1; index += 1) {
    await canonicalizeRelationshipIds(zip, `xl/worksheets/_rels/sheet${index}.xml.rels`, `xl/worksheets/sheet${index}.xml`);
  }
  for (const entry of Object.values(zip.files)) entry.date = new Date("1980-01-01T00:00:00Z");
  const finalBytes = await zip.generateAsync({ type: "nodebuffer", compression: "DEFLATE", compressionOptions: { level: 9 }, platform: "DOS" });
  await fs.writeFile(args.workbook, finalBytes);
  await fs.unlink(artifactToolOutput);
  await fs.rm(`${artifactToolOutput}.inspect.ndjson`, { force: true });
}

await main();
