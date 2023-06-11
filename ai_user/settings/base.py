import json
import logging

import discord
import openai
from redbot.core import checks, commands

from ai_user.abc import MixinMeta
from ai_user.settings.image import ImageSettings
from ai_user.settings.prompt import PromptSettings
from ai_user.settings.response import ResponseSettings
from ai_user.settings.triggers import TriggerSettings

logger = logging.getLogger("red.bz_cogs.ai_user")


class Settings(PromptSettings, ImageSettings, ResponseSettings, TriggerSettings, MixinMeta):

    @commands.group()
    @commands.guild_only()
    async def ai_user(self, _):
        """ Utilize OpenAI to reply to messages and images in approved channels"""
        pass

    @ai_user.command(aliases=["lobotomize"])
    async def forget(self, ctx: commands.Context):
        """ Forces the bot to forget the current conversation up to this point

            This is useful if the LLM is stuck doing unwanted behaviour or giving undesirable results.
            See `[p]ai_user triggers public_forget` to allow non-admins to use this command.
        """
        if not ctx.channel.permissions_for(ctx.author).manage_messages\
                and not await self.config.guild(ctx.guild).public_forget():
            return await ctx.react_quietly("❌")

        self.override_prompt_start_time[ctx.guild.id] = ctx.message.created_at
        await ctx.react_quietly("✅")

    @ai_user.command(aliases=["settings", "showsettings"])
    async def config(self, ctx: commands.Context):
        """ Returns current config

            (Current config per server)
        """
        config = await self.config.guild(ctx.guild).get_raw()
        whitelist = await self.config.guild(ctx.guild).channels_whitelist()
        channels = [f"<#{channel_id}>" for channel_id in whitelist]

        embed = discord.Embed(title="AI User Settings", color=await ctx.embed_color())

        embed.add_field(name="Model", inline=True, value=config['model'])
        embed.add_field(name="Reply Percent", inline=True, value=f"{config['reply_percent'] * 100:.2f}%")
        embed.add_field(name="Scan Images", inline=True, value=config['scan_images'])
        embed.add_field(name="Scan Image Mode", inline=True, value=config['scan_images_mode'])
        embed.add_field(name="Scan Image Max Size", inline=True,
                        value=f"{config['max_image_size'] / 1024 / 1024:.2f} MB")
        embed.add_field(name="Max History Size", inline=True, value=f"{config['messages_backread']} messages")
        embed.add_field(name="Max History Gap", inline=True, value=f"{config['messages_backread_seconds']} seconds")
        embed.add_field(name="Always Reply if Pinged", inline=True, value=config['reply_to_mentions_replies'])
        embed.add_field(name="Public Forget Command", inline=True, value=config['public_forget'])
        embed.add_field(name="Whitelisted Channels", inline=False, value=' '.join(channels) if channels else "None")

        regex_embed = discord.Embed(title="AI User Regex Settings", color=await ctx.embed_color())
        removelist_regexes = config['removelist_regexes']
        if isinstance(config['removelist_regexes'], list):
            total_length = 0
            removelist_regexes = []

            for item in config['removelist_regexes']:
                if total_length + len(item) <= 1000:
                    removelist_regexes.append(item)
                    total_length += len(item)
                else:
                    removelist_regexes.append("More regexes not shown...")
                    break

        blocklist_regexes = config['blocklist_regexes']
        if isinstance(config['blocklist_regexes'], list):
            total_length = 0
            blocklist_regexes = []

            for item in config['blocklist_regexes']:
                if total_length + len(item) <= 1000:
                    blocklist_regexes.append(item)
                    total_length += len(item)
                else:
                    blocklist_regexes.append("More regexes not shown...")
                    break

        regex_embed.add_field(name="Block list", value=f"`{blocklist_regexes}`")
        regex_embed.add_field(name="Remove list", value=f"`{removelist_regexes}`")
        regex_embed.add_field(name="Ignore Regex", value=f"`{config['ignore_regex']}`")

        await ctx.send(embed=embed)
        return await ctx.send(embed=regex_embed)

    @ai_user.command()
    @checks.is_owner()
    async def percent(self, ctx: commands.Context, percent: float):
        """ Change the bot's response chance

            (Setting is per server)
        """
        await self.config.guild(ctx.guild).reply_percent.set(percent / 100)
        self.reply_percent[ctx.guild.id] = percent / 100
        embed = discord.Embed(
            title="Chance that the bot will reply on this server is now:",
            description=f"{percent:.2f}%",
            color=await ctx.embed_color())
        return await ctx.send(embed=embed)

    @ai_user.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def add(self, ctx: commands.Context, channel: discord.TextChannel):
        """ Adds a channel to the whitelist

        **Arguments**
            - `channel` A mention of the channel
        """
        if not channel:
            return await ctx.send("Invalid channel mention, use #channel")
        new_whitelist = await self.config.guild(ctx.guild).channels_whitelist()
        if channel.id in new_whitelist:
            return await ctx.send("Channel already in whitelist")
        new_whitelist.append(channel.id)
        await self.config.guild(ctx.guild).channels_whitelist.set(new_whitelist)
        self.channels_whitelist[ctx.guild.id] = new_whitelist
        embed = discord.Embed(title="The server whitelist is now:", color=await ctx.embed_color())
        channels = [f"<#{channel_id}>" for channel_id in new_whitelist]
        embed.description = "\n".join(channels) if channels else "None"
        return await ctx.send(embed=embed)

    @ai_user.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def remove(self, ctx: commands.Context, channel: discord.TextChannel):
        """ Remove a channel from the whitelist

        **Arguments**
            - `channel` A mention of the channel
        """
        if not channel:
            return await ctx.send("Invalid channel mention, use #channel")
        new_whitelist = await self.config.guild(ctx.guild).channels_whitelist()
        if channel.id not in new_whitelist:
            return await ctx.send("Channel not in whitelist")
        new_whitelist.remove(channel.id)
        await self.config.guild(ctx.guild).channels_whitelist.set(new_whitelist)
        self.channels_whitelist[ctx.guild.id] = new_whitelist
        embed = discord.Embed(title="The server whitelist is now:", color=await ctx.embed_color())
        channels = [f"<#{channel_id}>" for channel_id in new_whitelist]
        embed.description = "\n".join(channels) if channels else "None"
        return await ctx.send(embed=embed)

    @ai_user.command()
    @checks.is_owner()
    async def model(self, ctx: commands.Context, model: str):
        """ Changes chat completion model

             To see a list of available models, use `[p]ai_user model list`
             (Setting is per server)
        """
        if not openai.api_key:
            await self.initalize_openai(ctx)

        models_list = openai.Model.list()

        if openai.api_base.startswith("https://api.openai.com/"):
            gpt_models = [model.id for model in models_list['data'] if model.id.startswith('gpt')]
        else:
            gpt_models = [model.id for model in models_list['data']]

        if model == 'list':
            embed = discord.Embed(title="Available Models", color=await ctx.embed_color())
            embed.description = '\n'.join([f"`{model}`" for model in gpt_models])
            return await ctx.send(embed=embed)

        if model not in gpt_models:
            await ctx.send(":warning: Not a valid model! :warning:")
            embed = discord.Embed(title="Available Models", color=await ctx.embed_color())
            embed.description = '\n'.join([f"`{model}`" for model in gpt_models])
            return await ctx.send(embed=embed)

        await self.config.guild(ctx.guild).model.set(model)
        embed = discord.Embed(
            title="This server's chat model is now set to:",
            description=model,
            color=await ctx.embed_color())
        return await ctx.send(embed=embed)

    @ai_user.command(name="parameters")
    @checks.is_owner()
    async def parameters(self, ctx: commands.Context, *, json_block: str):
        """ Set parameters for an endpoint using a JSON code block


            To reset parameters to default, use `[p]ai_user parameters reset`
            To show current parameters, use `[p]ai_user parameters show`

            Example command:
            `[p]ai_user parameters ```{"frequency_penalty": 2.0, "max_tokens": 200, "logit_bias":{"88": -100}}``` `

            See [here](https://platform.openai.com/docs/api-reference/chat/create) for possible parameters
            (Setting is per server)
        """

        if json_block in ['reset', 'clear']:
            await self.config.guild(ctx.guild).parameters.set(None)
            return await ctx.send("Parameters reset to default")

        embed = discord.Embed(title="Custom Parameters", color=await ctx.embed_color())
        embed.add_field(
            name=":warning: Warning :warning:", value="No checks were done to see if parameters were compatible", inline=False)

        if json_block in ['show', 'list']:
            data = await self.config.guild(ctx.guild).parameters()
            embed.add_field(name="Parameters", value=f"```{json.dumps(data, indent=4)}```", inline=False)
            return await ctx.send(embed=embed)

        if not json_block.startswith("```"):
            return await ctx.send(":warning: Please use a code block (`` eg. ```json ``)")

        json_block = json_block.replace("```json", "").replace("```", "")

        try:
            data = json.loads(json_block)
            await self.config.guild(ctx.guild).parameters.set(data)
        except json.JSONDecodeError:
            return await ctx.channel.send("Invalid JSON format!")

        embed.add_field(name="Parameters", value=f"```{json.dumps(data, indent=4)}```", inline=False)
        return await ctx.send(embed=embed)
