"""
Alert system for generating and formatting low volatility alerts.
"""
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
import requests
import json
from config import Config


@dataclass
class Alert:
    """Represents a single alert."""
    symbol: str
    name: str
    timeframe: str
    alert_type: str  # 'strong' or 'weak'
    rsi_value: float
    timestamp: datetime

    def format_message(self) -> str:
        """Format the alert message."""
        # Use name for Hong Kong stocks, symbol for others
        display_name = 'HK ' + self.symbol.rstrip('.HK') + ' ' + self.name if '.HK' in self.symbol else self.symbol

        if self.alert_type == 'strong':
            return f"[偏强提醒] {display_name} 在 {self.timeframe} 级别 出现低波动且偏强（RSI={self.rsi_value:.1f}）"
        else:
            return f"[偏弱提醒] {display_name} 在 {self.timeframe} 级别 出现低波动且偏弱（RSI={self.rsi_value:.1f}）"


class AlertSystem:
    """Alert generation and notification system."""

    def __init__(self, config: Config):
        self.config = config
        self.webhook_url = config.feishu_webhook_url

    def generate_alert(self, symbol: str, name: str, timeframe: str, rsi_value: float,
                      is_low_volatility: bool) -> Optional[Alert]:
        """
        Generate an alert if conditions are met.

        Args:
            symbol: Stock symbol
            name: Stock/ETF name
            timeframe: Timeframe ('4h' or '1d')
            rsi_value: Current RSI value
            is_low_volatility: Whether low volatility is detected

        Returns:
            Alert object if conditions met, None otherwise
        """
        if not is_low_volatility:
            return None

        # Determine alert type based on RSI
        if rsi_value >= self.config.rsi_strong_threshold:
            alert_type = 'strong'
        else:
            alert_type = 'weak'

        return Alert(
            symbol=symbol,
            name=name,
            timeframe=timeframe,
            alert_type=alert_type,
            rsi_value=rsi_value,
            timestamp=datetime.now()
        )

    def send_wechat_notification(self, message: str) -> bool:
        """
        Send notification via Feishu webhook.

        Args:
            message: Message to send

        Returns:
            True if successful, False otherwise
        """
        if not self.webhook_url:
            print("No Feishu webhook URL configured")
            return False

        try:
            payload = {
                "msg_type": "text",
                "content": {
                    "text": message
                }
            }

            response = requests.post(
                self.webhook_url,
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=30
            )

            if response.status_code == 200:
                result = response.json()
                if result.get('code') == 0:
                    print(f"Feishu notification sent successfully: {message}")
                    return True
                else:
                    print(f"Feishu API error: {result}")
                    return False
            else:
                print(f"HTTP error {response.status_code}: {response.text}")
                return False
        except requests.exceptions.RequestException as e:
            print(f"Error sending Feishu notification: {e}")
            return False
        except Exception as e:
            print(f"Unexpected error sending notification: {e}")
            return False

    def send_wechat_markdown(self, message: str) -> bool:
        """
        Send notification via Feishu webhook (card format).

        Args:
            message: Message to send

        Returns:
            True if successful, False otherwise
        """
        if not self.webhook_url:
            print("No Feishu webhook URL configured")
            return False

        try:
            payload = {
                "msg_type": "interactive",
                "card": {
                    "elements": [{
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": message
                        }
                    }]
                }
            }

            response = requests.post(
                self.webhook_url,
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=30
            )

            if response.status_code == 200:
                result = response.json()
                if result.get('code') == 0:
                    print(f"Feishu notification sent successfully: {message}")
                    return True
                else:
                    print(f"Feishu API error: {result}")
                    return False
            else:
                print(f"HTTP error {response.status_code}: {response.text}")
                return False
        except requests.exceptions.RequestException as e:
            print(f"Error sending Feishu notification: {e}")
            return False
        except Exception as e:
            print(f"Unexpected error sending notification: {e}")
            return False

    def send_alert(self, alert: Alert) -> bool:
        """
        Send a single alert.

        Args:
            alert: Alert to send

        Returns:
            True if successful, False otherwise
        """
        message = alert.format_message()
        return self.send_wechat_notification(message)

    def send_batch_alerts(self, alerts: List[Alert]) -> Dict[str, int]:
        """
        Send multiple alerts in batch.

        Args:
            alerts: List of alerts to send

        Returns:
            Dictionary with success/failure counts
        """
        results = {"success": 0, "failure": 0}

        if not alerts:
            return results

        # Group alerts by type for better formatting
        strong_alerts = [a for a in alerts if a.alert_type == 'strong']
        weak_alerts = [a for a in alerts if a.alert_type == 'weak']

        messages = []

        if strong_alerts:
            strong_msg = "[偏强提醒]\n" + "\n".join([
                f"{a.name + ' ' + a.symbol if '.HK' in a.symbol else a.symbol} ({a.timeframe}) RSI={a.rsi_value:.1f}"
                for a in strong_alerts
            ])
            messages.append(strong_msg)

        if weak_alerts:
            weak_msg = "[偏弱提醒]\n" + "\n".join([
                f"{a.name + ' ' + a.symbol if '.HK' in a.symbol else a.symbol} ({a.timeframe}) RSI={a.rsi_value:.1f}"
                for a in weak_alerts
            ])
            messages.append(weak_msg)

        # Send each message
        for message in messages:
            if self.send_wechat_notification(message):
                results["success"] += 1
            else:
                results["failure"] += 1

        return results

    def format_summary_message(self, alerts: List[Alert],
                              market_conditions: Dict[str, Tuple[bool, Dict[str, bool]]]) -> str:
        """
        Format a summary message with market conditions and alerts.

        Args:
            alerts: List of generated alerts
            market_conditions: Market condition results

        Returns:
            Formatted summary message
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Market condition summary
        market_summary = []
        for timeframe, (is_bearish, etf_conditions) in market_conditions.items():
            bearish_etfs = [symbol for symbol, is_bearish in etf_conditions.items() if is_bearish]
            market_summary.append(f"{timeframe}: {len(bearish_etfs)}/{len(etf_conditions)} ETFs bearish")

        # Alert summary
        strong_count = len([a for a in alerts if a.alert_type == 'strong'])
        weak_count = len([a for a in alerts if a.alert_type == 'weak'])

        summary = f"""美股监控报告 - {timestamp}

市场条件:
{chr(10).join(market_summary)}

低波动提醒:
- 偏强: {strong_count} 只
- 偏弱: {weak_count} 只
- 总计: {len(alerts)} 只

详细提醒:
"""

        # Add individual alerts
        for alert in alerts:
            summary += f"{alert.format_message()}\n"

        return summary.strip()
