from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from optimized_news_filter import build_dedupe_key, build_optimized_push_text, evaluate_optimized_news  # noqa: E402
from news_impact_classifier import format_impact_for_push, normalize_impact_payload, parse_json_tolerant  # noqa: E402


def flash(content: str) -> dict:
    return {"type": "flash", "time": "2026-05-30 00:00:00", "data": {"content": content}, "extras": {"ad": False}}


def assert_decision(name: str, msg: dict, expected: str) -> None:
    evaluation = evaluate_optimized_news(msg)
    actual = evaluation["decision"]
    if actual != expected:
        raise AssertionError(f"{name}: expected={expected} actual={actual} evaluation={evaluation}")


def main() -> int:
    assert_decision("crypto", flash("美国SEC批准比特币现货ETF期权上市，BTC短线拉升。"), "push")
    assert_decision("macro", flash("美国CPI低于预期，美债收益率下行，纳指期货拉升。"), "push")
    assert_decision("middle_east", flash("伊朗称将回应以色列袭击，霍尔木兹海峡风险上升。"), "push")
    assert_decision("trump_immigration_noise", flash("美国总统特朗普表示正在讨论新的移民计划。"), "skip")
    assert_decision(
        "trump_russia_contact_noise",
        flash("据俄新社：俄罗斯德米特里耶夫表示，俄罗斯本周将与美国总统特使威特科夫和特朗普女婿库什纳进行接触。"),
        "skip",
    )
    assert_decision("trump_russia_sanction_kept", flash("美国总统特朗普表示，将考虑对俄罗斯实施新制裁。"), "push")
    assert_decision("local_battle_kept", flash("以色列国防军称在黎巴嫩南部打击真主党目标。"), "push")
    assert_decision("local_ceasefire_kept", flash("黎巴嫩总统府称，真主党已同意美国关于相互停止袭击的提议。"), "push")
    assert_decision("local_humanitarian_kept", flash("联合国警告黎以冲突激化，贝鲁特南郊居民因以军撤离令逃离。"), "push")
    assert_decision("france_local_battle_kept", flash("法国总理表示，以色列应停止在黎巴嫩境内的军事行动。"), "push")
    assert_decision("foreign_macro_context", flash("瑞典央行行长表示，中东战争正在为未来通胀带来风险。"), "skip")
    assert_decision(
        "trump_kennedy_center_noise",
        flash("美国法官裁定将特朗普名字从肯尼迪中心移除，该中心更名争议遭到民主党反对。"),
        "skip",
    )
    assert_decision(
        "company_middle_east_false_positive",
        flash("众鑫股份在互动平台表示，公司中东业务营收占整体比重较小，美伊冲突未带来重大经营影响。"),
        "skip",
    )
    assert_decision("fed_low_info_quote", flash("美联储戴利：政策处于良好状态。已做好双向应对准备。"), "skip")
    assert_decision("fed_rate_risk_kept", flash("美联储洛根：越来越担心今年晚些时候可能需要提高利率。"), "push")
    assert_decision("fannie_mortgage_rate_noise", flash("房利美：6月4日当周，美国抵押贷款利率小幅下降至6.48%。"), "skip")
    assert_decision(
        "us_mortgage_rate_article_noise",
        flash(
            "【美国上周抵押贷款利率小幅下跌】金十数据6月5日讯，上周，美国抵押贷款利率略有下降，"
            "因为卖家难以找到愿意接受其报价的买家。据房地美数据，30年期固定贷款利率均值从6.53%降至6.48%。"
            "随着伊朗战争引发的经济不确定性推高通胀预期，并导致住房贷款利率居高不下，销售旺季正面临高昂借贷成本的压力。"
            "库存增长速度超过需求，导致全国各地许多卖家难以吸引买家出价。Redfin房产经纪人表示，"
            "高昂的汽油价格和生活成本的上升，使得潜在买家更不愿推高房价。"
        ),
        "skip",
    )
    assert_decision(
        "gold_council_commentary_noise",
        flash("【世界黄金协会：实物市场降温叠加能源风险 黄金或延续疲弱表现】世界黄金协会：全球黄金ETF资金流入在5月表现疲弱，短期内最大的风险可能来自能源市场。"),
        "skip",
    )
    assert_decision("oil_price_move_not_commentary", flash("WTI原油期货日内暴涨8.00%，现报94.35美元/桶。"), "skip")
    assert_decision("digest", flash("金十数据整理：欧盘美盘重要新闻汇总，伊朗、特朗普、黄金和原油消息一览。"), "skip")
    assert_decision("noise", flash("某公司发布季度财报，营收同比增长。"), "skip")
    assert_decision("vip", flash("金十VIP会员专享，点击查看详情。"), "skip")
    assert_decision("flash_list", {"type": "flash", "data": [{"title": "伊朗消息"}, {"title": "黄金消息"}]}, "skip")

    html_msg = flash("<b>美国总统特朗普表示，伊朗谈判仍在继续。</b>")
    html_eval = evaluate_optimized_news(html_msg)
    if "<" in html_eval["text"] or ">" in html_eval["text"]:
        raise AssertionError(f"html was not stripped from evaluation text: {html_eval}")
    push_text = build_optimized_push_text(html_msg, "2026-05-30T00:00:00+08:00", html_eval)
    if "<b>" in push_text or "</b>" in push_text:
        raise AssertionError(f"html was not stripped from push text: {push_text}")

    if build_dedupe_key(" BTC 突破！") != build_dedupe_key("BTC突破"):
        raise AssertionError("dedupe normalization failed")

    parsed = parse_json_tolerant(
        'DeepSeek判断如下：```json\n{"btc":{"impact":"bullish","reason":"流动性改善"},'
        '"gold":{"impact":"neutral","reason":"缺少直接线索"}}\n```'
    )
    impact = normalize_impact_payload(parsed)
    push_impact = format_impact_for_push(impact)
    expected_impact = "BTC：利多\n黄金：中性\n原因：BTC 流动性改善；黄金 缺少直接线索"
    if push_impact != expected_impact:
        raise AssertionError(f"impact formatting failed: {push_impact}")

    print("filter_regression_test=passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
