
import discord

from security.approval import (
    approve_request,
    cancel_request,
    get_approval_request,
    is_expired,
)
from security.actions import (
    ActionRequest,
    can_execute_after_approval,
)
from ai.action_executor import execute_action
from security.policies import get_safety_decision


class ApprovalView(discord.ui.View):
    def __init__(
        self,
        request_id: str,
        allowed_user_id: int,
        guild: discord.Guild,
        timeout: float = 300,
    ):
        super().__init__(timeout=timeout)

        if not isinstance(request_id, str) or not request_id.strip():
            raise ValueError("request_id must be a non-empty string.")

        if type(allowed_user_id) is not int or allowed_user_id <= 0:
            raise ValueError("allowed_user_id must be a positive integer.")

        if guild is None:
            raise ValueError("guild is required.")

        request = get_approval_request(request_id)

        if request is None:
            raise ValueError("Approval request does not exist.")

        if request.guild_id != guild.id:
            raise ValueError("Approval request belongs to another server.")

        if request.approver_id != allowed_user_id:
            raise ValueError("Approver does not match the approval request.")

        if allowed_user_id != guild.owner_id:
            raise ValueError("Only the current server owner can approve.")

        self.request_id = request_id
        self.allowed_user_id = allowed_user_id
        self.guild = guild

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        request = get_approval_request(self.request_id)

        if (
            interaction.guild_id != self.guild.id
            or self.guild.owner_id != self.allowed_user_id
            or interaction.user.id != self.allowed_user_id
            or request is None
            or request.guild_id != self.guild.id
            or request.approver_id != self.allowed_user_id
        ):
            await interaction.response.send_message(
                "You are not authorized to approve this request "
                "from this server.",
                ephemeral=True,
            )
            return False

        return True

    async def show_expired(
        self,
        interaction: discord.Interaction,
    ):
        await interaction.response.edit_message(
            content=(
                "This approval request has expired. "
                "Please create a new request if the action "
                "is still needed."
            ),
            embed=None,
            view=None,
        )

    @discord.ui.button(
        label="Confirm",
        style=discord.ButtonStyle.success,
        emoji="✅",
    )
    async def confirm(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        request = get_approval_request(self.request_id)

        if request is None:
            await interaction.response.edit_message(
                content="This approval request no longer exists.",
                embed=None,
                view=None,
            )
            return

        if (
            request.guild_id != self.guild.id
            or request.approver_id != self.allowed_user_id
            or self.guild.owner_id != self.allowed_user_id
        ):
            await interaction.response.edit_message(
                content=(
                    "This request's server or approver binding "
                    "is no longer valid."
                ),
                embed=None,
                view=None,
            )
            return

        if is_expired(self.request_id):
            await self.show_expired(interaction)
            return

        if request.cancelled:
            await interaction.response.edit_message(
                content="This request has already been cancelled.",
                embed=None,
                view=None,
            )
            return

        if request.approved or request.status != "pending":
            await interaction.response.edit_message(
                content="This request has already been used.",
                embed=None,
                view=None,
            )
            return

        action_request = ActionRequest(
            action=request.action,
            target_id=request.target_id,
            target_name=request.target_name,
            reason=request.reason,
            data=request.data,
        )

        decision_allowed = can_execute_after_approval(action_request)
        decision = get_safety_decision(request.action)

        if (
            not decision_allowed
            or not decision.get("allowed")
            or not decision.get("requires_approval")
            or decision.get("policy") != "approval"
        ):
            await interaction.response.edit_message(
                content=(
                    "Action blocked.\n\n"
                    "The security policy does not permit "
                    "this action through the approval workflow."
                ),
                embed=None,
                view=None,
            )
            return

        if not approve_request(self.request_id):
            if is_expired(self.request_id):
                await self.show_expired(interaction)
                return

            await interaction.response.edit_message(
                content="This request could not be approved.",
                embed=None,
                view=None,
            )
            return

        print(
            f"APPROVAL: Request {self.request_id} approved "
            f"by {interaction.user.id}."
        )

        try:
            await interaction.response.defer()
        except discord.HTTPException as error:
            print(f"APPROVAL: Failed to acknowledge confirmation: {error!r}")
            return

        await self.execute_approved_action(interaction, request)

    async def execute_approved_action(
        self,
        interaction: discord.Interaction,
        request,
    ):
        action = {
            "action": request.action,
            **request.data,
        }

        try:
            success = await execute_action(
                self.guild,
                action,
                reason=request.reason,
                approval_request_id=self.request_id,
            )
        except Exception as error:
            print(f"APPROVAL: Unexpected execution error: {error!r}")
            success = False

        if not success:
            await interaction.edit_original_response(
                content=(
                    "The request was approved, but the action "
                    "could not be completed.\n\n"
                    "Check the bot's logs, permissions, target, "
                    "and approval status."
                ),
                embed=None,
                view=None,
            )
            return

        if request.action == "move_channel":
            channel_id = request.data.get("channel_id")
            category_id = request.data.get("category_id")

            channel = self.guild.get_channel(channel_id)
            category = self.guild.get_channel(category_id)

            if channel is None:
                await interaction.edit_original_response(
                    content=(
                        "The action completed, but the channel "
                        "could no longer be found."
                    ),
                    embed=None,
                    view=None,
                )
                return

            category_name = (
                category.name
                if isinstance(category, discord.CategoryChannel)
                else "Unknown Category"
            )

            embed = discord.Embed(
                title="Channel Moved",
                description=(
                    f"**Channel:** {channel.mention}\n"
                    f"**To:** `{category_name}`\n"
                    f"**Reason:** {request.reason}"
                ),
                color=discord.Color.green(),
            )
            embed.set_footer(text=f"Approved by {interaction.user}")

            await interaction.edit_original_response(
                embed=embed,
                view=None,
            )
            return

        if request.action == "rename_channel":
            channel_id = request.data.get("channel_id")
            channel = self.guild.get_channel(channel_id)

            channel_name = (
                channel.mention
                if channel is not None
                else "Unknown channel"
            )

            embed = discord.Embed(
                title="Channel Renamed",
                description=(
                    f"**Channel:** {channel_name}\n"
                    f"**New Name:** "
                    f"`{request.data.get('new_name', '')}`\n"
                    f"**Reason:** {request.reason}"
                ),
                color=discord.Color.green(),
            )
            embed.set_footer(text=f"Approved by {interaction.user}")

            await interaction.edit_original_response(
                embed=embed,
                view=None,
            )
            return

        await interaction.edit_original_response(
            content=(
                f"The action `{request.action}` "
                "was approved and executed."
            ),
            embed=None,
            view=None,
        )

    @discord.ui.button(
        label="Cancel",
        style=discord.ButtonStyle.danger,
        emoji="❌",
    )
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        request = get_approval_request(self.request_id)

        if request is None:
            await interaction.response.edit_message(
                content="This approval request no longer exists.",
                embed=None,
                view=None,
            )
            return

        if (
            request.guild_id != self.guild.id
            or request.approver_id != self.allowed_user_id
            or self.guild.owner_id != self.allowed_user_id
        ):
            await interaction.response.edit_message(
                content="This request's security binding is invalid.",
                embed=None,
                view=None,
            )
            return

        if is_expired(self.request_id):
            await self.show_expired(interaction)
            return

        if request.approved or request.status != "pending":
            await interaction.response.edit_message(
                content="This request has already been used.",
                embed=None,
                view=None,
            )
            return

        if request.cancelled:
            await interaction.response.edit_message(
                content="This request has already been cancelled.",
                embed=None,
                view=None,
            )
            return

        if not cancel_request(self.request_id):
            if is_expired(self.request_id):
                await self.show_expired(interaction)
                return

            await interaction.response.edit_message(
                content="This request could not be cancelled.",
                embed=None,
                view=None,
            )
            return

        await interaction.response.edit_message(
            content="Action cancelled.",
            embed=None,
            view=None,
        )