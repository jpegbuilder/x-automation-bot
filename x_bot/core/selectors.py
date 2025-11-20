from dataclasses import dataclass, field
from typing import List


@dataclass
class XSelectors:

    # Follow buttons
    FOLLOW_BUTTONS: List[str] = field(default_factory=lambda: [
        "//button[@data-testid='placementTracking']//span[text()='Follow']",
        "//button[contains(@aria-label, 'Follow @')]",
        "//div[@data-testid='placementTracking']//button",
        "//span[text()='Follow']/ancestor::button",
        "//button[.//span[text()='Follow']]",
        "//*[@data-testid='follow']"
    ])

    # Success indicators
    SUCCESS_BUTTONS: List[str] = field(default_factory=lambda: [
        "//button[contains(@aria-label, 'Following')]",
        "//button[contains(text(), 'Following')]",
        "//button[contains(text(), 'Pending')]",
    ])

    # Suspension indicators
    SUSPENSION_SELECTORS: List[str] = field(default_factory=lambda: [
        "//h1[contains(text(), 'suspended')]",
        "//h2[contains(text(), 'suspended')]",
        "//span[contains(text(), 'Account suspended')]",
        "//*[contains(text(), 'This account has been suspended')]",
        "//span[contains(text(), 'Your account is suspended')]",
    ])

    SUSPENSION_KEYWORDS: List[str] = field(default_factory=lambda: [
        "account suspended",
        "your account is suspended",
        "this account has been suspended",
        "suspended account",
        "account has been suspended",
        "your account is suspended and is not permitted to follow users."
    ])

    # Follow block indicators
    FOLLOW_BLOCK_SELECTORS: List[str] = field(default_factory=lambda: [
        "//span[contains(text(), 'You are unable to follow more people')]",
        "//span[contains(text(), 'You have reached your daily limit')]",
        "//span[contains(text(), 'Sorry, you are rate limited. Please wait a few moments then try again.')]",
        "//*[contains(text(), 'Sorry, you are rate limited. Please wait a few moments then try again.')]",
        "//div[contains(text(), 'Try Again Later')]",
        "//div[contains(text(), 'Action Blocked')]",
        "//h2[contains(text(), 'Try Again Later')]",
        "//*[contains(text(), 'temporarily blocked')]",
    ])

    FOLLOW_BLOCK_KEYWORDS: List[str] = field(default_factory=lambda: [
        "try again later",
        "action blocked",
        "we restrict certain activity",
        "temporarily blocked",
        "slow down",
        "too many requests",
        "you have reached your daily limit",
    ])

    # Profile existence indicators
    PROFILE_ERROR_SELECTORS: List[str] = field(default_factory=lambda: [
        '//span[contains(text(), "doesn")]',
        '//span[contains(text(), "Doesn")]',
        '//*[contains(text(), "This account")]',
        '//*[contains(text(), "Account suspended")]',
        '//div[@data-testid="error-detail"]'
    ])

    PROFILE_INDICATORS: List[str] = field(default_factory=lambda: [
        "//button[contains(@aria-label, 'Follow')]",
        "//button[contains(text(), 'Following')]",
        "//div[@data-testid='UserDescription']",
        "//div[@data-testid='UserProfileHeader_Items']"
    ])

    # Protected account indicators
    PROTECTED_KEYWORDS: List[str] = field(default_factory=lambda: [
        "these posts are protected",
        "protected account",
        "only approved followers can see",
        "follow to see their posts",
        "this account is protected"
    ])

    PROTECTED_SELECTORS: List[str] = field(default_factory=lambda: [
        "//*[contains(text(), 'These posts are protected')]",
        "//*[contains(text(), 'Only approved followers')]",
        "//span[contains(text(), 'protected')]"
    ])

    # Non-existent profile keywords
    DOESNT_EXIST_KEYWORDS: List[str] = field(default_factory=lambda: [
        "this account doesn't exist",
        "account doesn't exist",
        "doesn't exist",
        "page doesn't exist",
        "this page doesn't exist"
    ])

# Pending
# A follow request has been sent to @JhoelGalla64110 and is pending their approval.