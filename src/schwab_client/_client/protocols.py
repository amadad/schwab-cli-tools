"""Shared structural protocols for the underlying schwab-py client."""

from __future__ import annotations

from typing import Protocol

from src.core.json_types import JsonObject, JsonValue


class SchwabResponse(Protocol):
    status_code: int
    headers: dict[str, str]
    text: str

    def raise_for_status(self) -> None: ...

    def json(self) -> JsonValue: ...


class AccountFields(Protocol):
    POSITIONS: str


class AccountNamespace(Protocol):
    Fields: AccountFields


class TransactionTypeNamespace(Protocol):
    DIVIDEND_OR_INTEREST: object

    def __call__(self, value: str) -> object: ...


class TransactionsNamespace(Protocol):
    TransactionType: TransactionTypeNamespace


class SchwabClientTransport(Protocol):
    Account: AccountNamespace
    Transactions: TransactionsNamespace

    def get_account_numbers(self) -> SchwabResponse: ...

    def get_account(self, account_hash: str, fields: str | None = None) -> SchwabResponse: ...

    def get_accounts(self, fields: str | None = None) -> SchwabResponse: ...

    def get_quote(self, symbol: str) -> SchwabResponse: ...

    def get_quotes(self, symbols: list[str]) -> SchwabResponse: ...

    def get_orders_for_account(self, account_hash: str) -> SchwabResponse: ...

    def get_order(self, order_id: int, account_hash: str) -> SchwabResponse: ...

    def get_transactions(
        self,
        account_hash: str,
        start_date: object,
        end_date: object,
        transaction_types: object,
    ) -> SchwabResponse:
        _ = transaction_types
        raise NotImplementedError

    def place_order(self, account_hash: str, order: JsonObject) -> SchwabResponse: ...

    def cancel_order(self, order_id: str, account_hash: str) -> SchwabResponse: ...
