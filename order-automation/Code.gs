// =============================================
// 発注自動化スクリプト - Google Apps Script
// =============================================

// --- シート名の設定 ---
const MASTER_SHEET_NAME = 'マスター';
const ORDER_LOG_SHEET_NAME = '注文ログ';

// --- スクリプトプロパティから取得（初期設定で登録する）---
function getSlackBotToken() {
  return PropertiesService.getScriptProperties().getProperty('SLACK_BOT_TOKEN');
}

// =============================================
// Slack Event API エンドポイント（Webアプリ）
// =============================================
function doPost(e) {
  const data = JSON.parse(e.postData.contents);

  // Slack URL verification（初回設定時のみ）
  if (data.type === 'url_verification') {
    return ContentService.createTextOutput(data.challenge);
  }

  // @メンション イベント
  if (data.event && data.event.type === 'app_mention') {
    const text = data.event.text;
    const user = data.event.user;
    const channel = data.event.channel;
    const ts = data.event.ts;

    const orderInfo = parseOrderMessage(text);

    if (!orderInfo) {
      replyToSlack(channel, ts, '注文内容を認識できませんでした。\n例: 「@発注bot スキャット20X-N 3個」のように入力してください。');
      return ContentService.createTextOutput('OK');
    }

    const productInfo = lookupProduct(orderInfo.productName);

    if (!productInfo) {
      replyToSlack(channel, ts,
        `「${orderInfo.productName}」はマスターシートで見つかりませんでした。\n商品名を確認するか、Googleフォームから注文してください。`
      );
      return ContentService.createTextOutput('OK');
    }

    logOrder(productInfo, orderInfo.quantity, `Slack:${user}`, 'Slack');
    replyToSlack(channel, ts,
      `✅ 注文を受け付けました。\n` +
      `製品名：${productInfo.name}\n` +
      `メーカー：${productInfo.maker}\n` +
      `品番：${productInfo.productNumber}\n` +
      `個数：${orderInfo.quantity}\n` +
      `発注業者：${productInfo.vendor}\n\n` +
      `次回の発注まとめ時にメール下書きを作成します。`
    );
  }

  return ContentService.createTextOutput('OK');
}

// =============================================
// Google Form 回答時のトリガー
// =============================================
function onFormSubmit(e) {
  const responses = e.response.getItemResponses();
  let productName = '';
  let quantity = 1;
  let requester = e.response.getRespondentEmail() || '不明';

  for (const response of responses) {
    const title = response.getItem().getTitle();
    const answer = String(response.getResponse()).trim();

    if (title.match(/商品|製品|試薬|品名/)) {
      productName = answer;
    } else if (title.match(/個数|数量|本数/)) {
      quantity = parseInt(answer) || 1;
    } else if (title.match(/氏名|名前|依頼者/)) {
      requester = answer;
    }
  }

  if (!productName) return;

  const productInfo = lookupProduct(productName);
  if (productInfo) {
    logOrder(productInfo, quantity, requester, 'Form');
  } else {
    // 見つからなかった場合はログシートにエラー行として記録
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    let logSheet = ss.getSheetByName(ORDER_LOG_SHEET_NAME);
    if (!logSheet) initLogSheet();
    logSheet = ss.getSheetByName(ORDER_LOG_SHEET_NAME);
    logSheet.appendRow([
      new Date(), productName, '---', '---', quantity,
      '---', requester, 'Form', '要確認（商品未登録）'
    ]);
  }
}

// =============================================
// メッセージ解析：商品名と個数を抽出
// =============================================
function parseOrderMessage(text) {
  // @メンション部分を除去
  const clean = text.replace(/<@[A-Z0-9]+>/g, '').trim();

  // 個数パターン（数字 + 単位 or 数字のみ）
  const quantityPattern = /(\d+)\s*(個|本|箱|袋|セット|枚|錠|g|mg|L|mL|ml|ケース)?/;
  const match = clean.match(quantityPattern);

  let quantity = 1;
  let productText = clean;

  if (match) {
    quantity = parseInt(match[1]);
    // 数量部分を取り除いて商品名だけ残す
    productText = clean.replace(match[0], '').trim();
  }

  // 不要なワードを除去
  productText = productText
    .replace(/注文|発注|お願い|ください|して|欲しい|頼む/g, '')
    .replace(/\s+/g, ' ')
    .trim();

  if (!productText) return null;

  return { productName: productText, quantity };
}

// =============================================
// マスターシートから商品検索（部分一致対応）
// =============================================
function lookupProduct(productName) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName(MASTER_SHEET_NAME);
  if (!sheet) return null;

  const data = sheet.getDataRange().getValues();
  const lower = productName.toLowerCase();

  // 完全一致を優先
  for (let i = 1; i < data.length; i++) {
    if (!data[i][0]) continue;
    if (String(data[i][0]).trim() === productName.trim()) {
      return buildProductInfo(data[i]);
    }
  }

  // 部分一致
  for (let i = 1; i < data.length; i++) {
    if (!data[i][0]) continue;
    const rowName = String(data[i][0]).toLowerCase();
    if (rowName.includes(lower) || lower.includes(rowName)) {
      return buildProductInfo(data[i]);
    }
  }

  return null;
}

function buildProductInfo(row) {
  return {
    name: row[0],           // 注文した商品
    maker: row[1],          // メーカー
    productNumber: row[2],  // 商品ナンバー
    standardQty: row[3],    // 個数（標準）
    vendor: row[4],         // 発注業者
    vendorEmail: row[5] || '',  // メールアドレス（列を追加した場合）
  };
}

// =============================================
// 注文ログシートに記録
// =============================================
function logOrder(productInfo, quantity, requester, source) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let logSheet = ss.getSheetByName(ORDER_LOG_SHEET_NAME);

  if (!logSheet) {
    initLogSheet();
    logSheet = ss.getSheetByName(ORDER_LOG_SHEET_NAME);
  }

  logSheet.appendRow([
    new Date(),
    productInfo.name,
    productInfo.maker,
    productInfo.productNumber,
    quantity,
    productInfo.vendor,
    requester,
    source,
    '未発注'
  ]);
}

function initLogSheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.insertSheet(ORDER_LOG_SHEET_NAME);
  sheet.appendRow([
    'タイムスタンプ', '商品名', 'メーカー', '品番',
    '個数', '発注業者', '依頼者', 'ソース', 'ステータス'
  ]);
  // ヘッダー行を固定
  sheet.setFrozenRows(1);
}

// =============================================
// 発注メール下書き作成（2週間ごとに自動実行）
// =============================================
function generateOrderDrafts() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const logSheet = ss.getSheetByName(ORDER_LOG_SHEET_NAME);
  if (!logSheet) return;

  const data = logSheet.getDataRange().getValues();

  // 「未発注」の注文を抽出
  const pending = [];
  for (let i = 1; i < data.length; i++) {
    if (data[i][8] === '未発注') {
      pending.push({ row: i + 1, ...rowToOrder(data[i]) });
    }
  }

  if (pending.length === 0) {
    Logger.log('未発注の注文はありません。');
    return;
  }

  // 発注業者ごとにグループ化
  const byVendor = {};
  for (const order of pending) {
    if (!byVendor[order.vendor]) byVendor[order.vendor] = [];
    byVendor[order.vendor].push(order);
  }

  // 業者ごとにGmail下書きを作成
  for (const [vendor, orders] of Object.entries(byVendor)) {
    createOrderDraft(vendor, orders);

    // ステータスを「下書き作成済み」に更新
    for (const order of orders) {
      logSheet.getRange(order.row, 9).setValue('下書き作成済み');
    }

    Logger.log(`下書き作成: ${vendor} (${orders.length}件)`);
  }
}

function rowToOrder(row) {
  return {
    productName: row[1],
    maker: row[2],
    productNumber: row[3],
    quantity: row[4],
    vendor: row[5],
    requester: row[6],
  };
}

function createOrderDraft(vendor, orders) {
  const today = new Date().toLocaleDateString('ja-JP', {
    year: 'numeric', month: 'long', day: 'numeric'
  });
  const subject = `【発注依頼】${vendor}（${today}）`;

  let body = `お世話になっております。\n\n`;
  body += `以下、${orders.length}点の製品のお見積りをお願いいたします。\n\n`;

  orders.forEach((order, i) => {
    body += `${i + 1}．\n`;
    body += `製品名：${order.productName}\n`;
    body += `メーカー：${order.maker}\n`;
    body += `品番：${order.productNumber}\n`;
    body += `個数：${order.quantity}\n\n`;
  });

  body += `何卒よろしくお願い申しあげます。`;

  // 下書き作成（宛先は空欄 → 送信前に手動で入力）
  GmailApp.createDraft('', subject, body);
}

// =============================================
// 時間トリガー登録（初回1回だけ手動実行）
// =============================================
function setupTriggers() {
  // 既存トリガーを削除
  ScriptApp.getProjectTriggers().forEach(t => ScriptApp.deleteTrigger(t));

  // 2週間ごと（月曜9時）に下書き作成
  ScriptApp.newTrigger('generateOrderDrafts')
    .timeBased()
    .onWeekDay(ScriptApp.WeekDay.MONDAY)
    .atHour(9)
    .everyWeeks(2)
    .create();

  Logger.log('トリガーを設定しました（隔週月曜 9時）');
}
