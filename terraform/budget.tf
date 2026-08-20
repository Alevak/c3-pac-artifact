# =============================================================================
# Бюджет-алерти: листи на 50%, 80%, 100% від ліміту + прогнозний алерт.
# Це "розтяжка": якщо забули знести кластер — дізнаєтесь за $12, а не за $500.
# =============================================================================

resource "aws_budgets_budget" "experiment" {
  name         = "${var.cluster_name}-budget"
  budget_type  = "COST"
  limit_amount = tostring(var.budget_limit_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  dynamic "notification" {
    for_each = [50, 80, 100]
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = [var.alert_email]
    }
  }

  # Прогнозний алерт: спрацьовує, коли AWS прогнозує перевищення до кінця місяця
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
  }
}
