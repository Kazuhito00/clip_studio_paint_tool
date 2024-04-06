#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import zlib
import copy
import time
import struct
import sqlite3
import logging

import numpy as np


class CspTool(object):

    def __init__(
            self,
            filepath,
            logger_name='Clip-Studio-File-Tool',
            log_filename=None,
            debug_level='WARNING',  # 'DEBUG', 'INFO', 'ERROR', 'CRITICAL'
    ):
        # Logger設定
        self.logger = logging.getLogger(logger_name)
        self.set_debug_level(log_filename, debug_level)

        # チャンクデータ保持用変数
        self.chunk_header = None
        self.chunk_external_list = []
        self.chunk_sqldb = None
        self.chunk_footer = None

        # 拡張子確認
        extension = os.path.splitext(filepath)[1]
        if extension != '.clip':
            self.logger.error(
                'It is not a Clip Studio Paint file (extension is not "clip")')
            return

        # clipファイル読み出し
        csf_info = self._read_clip_studio_file(filepath)
        self.chunk_external_list = csf_info[0]
        self.binary_data = csf_info[1]
        self.sqlite_binary_data = csf_info[2]

        # sqliteデータ読み出し
        sqlite_data = self._read_sqlite_data(self.sqlite_binary_data)
        self.canvas_preview_list = sqlite_data[0]
        self.layer_list = sqlite_data[1]
        self.layer_thumbnail_list = sqlite_data[2]
        self.offscreen_list = sqlite_data[3]
        self.mipmap_list = sqlite_data[4]
        self.mipmap_info_list = sqlite_data[5]

        return

    def get_layer_list(self):
        return self.layer_list

    def get_raster_data(self, canvas_id, layer_id):
        start_time = time.time()

        # 該当のExternal IDを取得
        external_id = self._get_external_id(canvas_id, layer_id)

        bgr_image, alpha_image, bgra_image = None, None, None
        if external_id is not None:
            # 該当のLayerThumbnailを取得
            layer_thumbnail_data = self._get_layer_thumbnail(
                canvas_id,
                layer_id,
            )

            # External Dataを取得
            external_data = self._get_layer_external_data(external_id)

            # External Dataから画像を取得
            image_width = layer_thumbnail_data['thumbnail_canvas_width']
            image_height = layer_thumbnail_data['thumbnail_canvas_height']
            if external_data is not None:
                bgr_image, alpha_image = self._get_image_from_external_data(
                    external_data,
                    image_width,
                    image_height,
                )

                # 画像とアルファ画像を結合
                temp_alpha_image = alpha_image.reshape([*alpha_image.shape, 1])
                bgra_image = np.concatenate([bgr_image, temp_alpha_image], 2)

        elapsed_time = (time.time() - start_time) * 1000
        self.logger.debug('get_raster_data():{:.2f}ms'.format(elapsed_time))

        return bgr_image, alpha_image, bgra_image

    def _read_clip_studio_file(self, filepath):
        self.logger.debug('_read_clip_studio_file(' + filepath + ')')

        # chunk_header = None
        chunk_external_list = []
        # chunk_sqldb = None
        # chunk_footer = None

        # チャンクデータとバイナリデータ読み出し
        chunk_data_info = self._read_chunk_data(filepath)
        chunk_data_list = chunk_data_info[0]
        binary_data = chunk_data_info[1]
        sqlite_binary_data = chunk_data_info[2]

        # chunk_header = chunk_data_list[0]
        chunk_external_list = chunk_data_list[1:-2]
        # chunk_sqldb = chunk_data_list[-2]
        # chunk_footer = chunk_data_list[-1]

        return chunk_external_list, binary_data, sqlite_binary_data

    def _read_chunk_data(self, filepath):
        chunk_data_list = []
        binary_data = None
        sqlite_binary_data = None

        self.logger.debug('_read_chunk_data(' + filepath + ')')

        with open(filepath, mode='rb') as binary_file:
            binary_data = binary_file.read()
            data_size = len(binary_data)

            offset = 0

            # 8バイト：マジックナンバー
            csf_magic_number = struct.unpack_from('8s', binary_data, offset)[0]
            csf_magic_number = csf_magic_number.decode()
            offset += 8
            self.logger.debug('    CSF Magic Number:' + csf_magic_number)

            # 16バイト：読み飛ばし
            offset += 16

            while offset < data_size:
                # チャンク開始位置
                chunk_start_position = offset

                # 8バイト：チャンクタイプ
                chunk_type = struct.unpack_from('8s', binary_data, offset)[0]
                chunk_type = chunk_type.decode()
                offset += 8

                # ビッグエンディアン8バイト：チャンクサイズ
                chunk_size = struct.unpack_from('>Q', binary_data, offset)[0]
                offset += 8

                # チャンクサイズ読み飛ばし
                offset += chunk_size

                # チャンク終了位置
                chunk_end_position = offset

                chunk_data = {
                    'type': chunk_type,
                    'size': chunk_size,
                    'chunk_start_position': chunk_start_position,
                    'chunk_end_position': chunk_end_position,
                }
                chunk_data_list.append(chunk_data)

                self.logger.debug('    ' + str(chunk_data))

            # SQLiteチャンク開始位置確認
            sqlite_chunk_start_position = 0
            for chunk_info in chunk_data_list:
                if chunk_info['type'] == 'CHNKSQLi':
                    sqlite_chunk_start_position = chunk_info[
                        'chunk_start_position']

            sqlite_offset = sqlite_chunk_start_position + 16

            # SQLiteファイル保存
            sqlite_binary_data = copy.deepcopy(binary_data[sqlite_offset:])

        return chunk_data_list, binary_data, sqlite_binary_data

    def _read_sqlite_data(
        self,
        sqlite_binary_data,
        temp_db_filename='__temp__.db',
    ):
        self.logger.debug('_read_sqlite_data()')

        # SQLiteファイル 一次保存
        with open(temp_db_filename, mode="wb") as f:
            f.write(sqlite_binary_data)

        # dbファイル接続
        connect = sqlite3.connect(temp_db_filename)

        # CanvasPreview
        self.logger.debug('    CanvasPreview')
        canvas_preview_list = []
        query_results = self._exec_sqlite_query(
            connect,
            "SELECT MainId, CanvasId, ImageData, ImageWidth, ImageHeight FROM CanvasPreview;",
        )
        for query_result in query_results:
            main_id = query_result[0]
            canvas_id = query_result[1]
            image_data = query_result[2]
            image_width = query_result[3]
            image_height = query_result[4]

            canvas_preview_data = {
                'main_id': main_id,
                'canvas_id': canvas_id,
                'image_data': image_data,
                'image_width': image_width,
                'image_height': image_height,
            }
            canvas_preview_list.append(canvas_preview_data)

            self.logger.debug('        {' + "'main_id':" + str(main_id) +
                              ", 'canvas_id':" + str(canvas_id) +
                              ", 'image_width':" + str(image_width) +
                              ", 'image_height':" + str(image_height) + '}')

        # Layer
        self.logger.debug('    Layer')
        layer_list = []
        query_results = self._exec_sqlite_query(
            connect,
            "SELECT MainId, CanvasId, LayerName, LayerUuid, LayerRenderMipmap, LayerRenderThumbnail FROM Layer;",
        )
        for query_result in query_results:
            main_id = query_result[0]
            canvas_id = query_result[1]
            layer_name = query_result[2]
            layer_uuid = query_result[3]
            layer_render_mipmap = query_result[4]
            layer_render_thumbnail = query_result[5]

            layer_data = {
                'main_id': main_id,
                'canvas_id': canvas_id,
                'layer_name': layer_name,
                'layer_uuid': layer_uuid,
                'layer_render_mipmap': layer_render_mipmap,
                'layer_render_thumbnail': layer_render_thumbnail,
            }
            layer_list.append(layer_data)

            self.logger.debug('        ' + str(layer_data))

        # LayerThumbnail
        self.logger.debug('    LayerThumbnail')
        layer_thumbnail_list = []
        query_results = self._exec_sqlite_query(
            connect,
            "SELECT MainId, CanvasId, LayerId, ThumbnailCanvasWidth, ThumbnailCanvasHeight, ThumbnailOffscreen FROM LayerThumbnail;",
        )
        for query_result in query_results:
            main_id = query_result[0]
            canvas_id = query_result[1]
            layer_id = query_result[2]
            thumbnail_canvas_width = query_result[3]
            thumbnail_canvas_height = query_result[4]
            thumbnail_offscreen = query_result[5]

            layer_thumbnail_data = {
                'main_id': main_id,
                'canvas_id': canvas_id,
                'layer_id': layer_id,
                'thumbnail_canvas_width': thumbnail_canvas_width,
                'thumbnail_canvas_height': thumbnail_canvas_height,
                'thumbnail_offscreen': thumbnail_offscreen,
            }
            layer_thumbnail_list.append(layer_thumbnail_data)

            self.logger.debug('        ' + str(layer_thumbnail_data))

        # Offscreen
        self.logger.debug('    Offscreen')
        offscreen_list = []
        query_results = self._exec_sqlite_query(
            connect,
            "SELECT MainId, CanvasId, LayerId, BlockData FROM Offscreen;",
        )
        for query_result in query_results:
            main_id = query_result[0]
            canvas_id = query_result[1]
            layer_id = query_result[2]
            block_data = query_result[3].decode()

            offscreen_data = {
                'main_id': main_id,
                'canvas_id': canvas_id,
                'layer_id': layer_id,
                'block_data': block_data,
            }
            offscreen_list.append(offscreen_data)

            self.logger.debug('        ' + str(offscreen_data))

        # Mipmap
        self.logger.debug('    Mipmap')
        mipmap_list = []
        query_results = self._exec_sqlite_query(
            connect,
            "SELECT MainId, CanvasId, LayerId, MipmapCount, BaseMipmapInfo FROM Mipmap;",
        )
        for query_result in query_results:
            main_id = query_result[0]
            canvas_id = query_result[1]
            layer_id = query_result[2]
            mipmap_count = query_result[3]
            base_mipmap_info = query_result[4]

            mipmap_data = {
                'main_id': main_id,
                'canvas_id': canvas_id,
                'layer_id': layer_id,
                'mipmap_count': mipmap_count,
                'base_mipmap_info': base_mipmap_info,
            }
            mipmap_list.append(mipmap_data)

            self.logger.debug('        ' + str(mipmap_data))

        # MipmapInfo
        self.logger.debug('    MipmapInfo')
        mipmap_info_list = []
        query_results = self._exec_sqlite_query(
            connect,
            "SELECT MainId, CanvasId, LayerId, ThisScale, Offscreen, NextIndex FROM MipmapInfo;",
        )
        for query_result in query_results:
            main_id = query_result[0]
            canvas_id = query_result[1]
            layer_id = query_result[2]
            this_scale = query_result[3]
            offscreen = query_result[4]
            next_index = query_result[5]

            mipmap_info_data = {
                'main_id': main_id,
                'canvas_id': canvas_id,
                'layer_id': layer_id,
                'this_scale': this_scale,
                'offscreen': offscreen,
                'next_index': next_index,
            }
            mipmap_info_list.append(mipmap_info_data)

            self.logger.debug('        ' + str(mipmap_info_data))

        # dbファイルクローズ
        connect.close()

        # SQLite一時ファイル削除
        os.remove(temp_db_filename)

        return canvas_preview_list, layer_list, layer_thumbnail_list, offscreen_list, mipmap_list, mipmap_info_list

    def _exec_sqlite_query(
        self,
        connect,
        query,
    ):
        cursor = connect.cursor()
        cursor.execute(query)
        query_results = cursor.fetchall()
        cursor.close()

        return query_results

    def _get_external_id(self, canvas_id, layer_id):
        self.logger.debug('_get_external_id(' + str(canvas_id) + ',' +
                          str(layer_id) + ')')

        # Layer検索
        layer_data = None
        for temp_layer_data in self.layer_list:
            temp_layer_id = temp_layer_data['main_id']
            temp_canvas_id = temp_layer_data['canvas_id']
            if temp_layer_id == layer_id and temp_canvas_id == canvas_id:
                layer_data = temp_layer_data
                break
        self.logger.debug('    layer_data:' + str(layer_data))

        if layer_data is None:
            return None

        # LayerThumbnail検索
        layer_thumbnail_data = None
        for temp_layer_thumbnail_data in self.layer_thumbnail_list:
            temp_layer_id = temp_layer_thumbnail_data['main_id']
            temp_canvas_id = temp_layer_thumbnail_data['canvas_id']
            if temp_layer_id == layer_id and temp_canvas_id == canvas_id:
                layer_thumbnail_data = temp_layer_thumbnail_data
                break
        self.logger.debug('    layer_thumbnail_data:' +
                          str(layer_thumbnail_data))

        # MipMap検索
        mipmap_data = None
        for temp_mipmap_data in self.mipmap_list:
            temp_mipmap_id = temp_mipmap_data['main_id']
            mipmap_id = layer_data['layer_render_mipmap']
            if temp_mipmap_id == mipmap_id:
                mipmap_data = temp_mipmap_data
                break
        self.logger.debug('    mipmap_data:' + str(mipmap_data))

        # MipmapInfo検索
        mipmap_detail_data = None
        for temp_mipmap_detail_data in self.mipmap_info_list:
            temp_mipmap_info_id = temp_mipmap_detail_data['main_id']
            mipmap_info_id = mipmap_data['base_mipmap_info']
            if temp_mipmap_info_id == mipmap_info_id:
                mipmap_detail_data = temp_mipmap_detail_data
                break
        self.logger.debug('    mipmap_detail_data:' + str(mipmap_detail_data))

        # Offscreen検索
        offscreen_data = None
        for temp_offscreen_data in self.offscreen_list:
            temp_offscreen_id = temp_offscreen_data['main_id']
            offscreen_id = mipmap_detail_data['offscreen']
            if temp_offscreen_id == offscreen_id:
                offscreen_data = temp_offscreen_data
                break
        self.logger.debug('    offscreen_data:' + str(offscreen_data))

        # External Data ID
        external_data_id = offscreen_data['block_data']
        self.logger.debug('    external_data_id:' + str(external_data_id))

        return external_data_id

    def _get_layer_thumbnail(self, canvas_id, layer_id):
        # LayerThumbnail検索
        layer_thumbnail_data = None
        for temp_layer_thumbnail_data in self.layer_thumbnail_list:
            temp_layer_id = temp_layer_thumbnail_data['main_id']
            temp_canvas_id = temp_layer_thumbnail_data['canvas_id']
            if temp_layer_id == layer_id and temp_canvas_id == canvas_id:
                layer_thumbnail_data = temp_layer_thumbnail_data
                break

        return layer_thumbnail_data

    def _get_layer_external_data(self, external_id):
        self.logger.debug('_get_layer_external_data(' + str(external_id) + ')')

        # External Data IDを用いて該当のチャンクデータを取得
        target_chunk_data = None
        for chunk_data in self.chunk_external_list:
            if chunk_data['type'] != 'CHNKExta':
                continue

            temp_external_id = self._get_external_id_from_chunk(
                chunk_data,
                self.binary_data,
            )
            if temp_external_id == external_id:
                target_chunk_data = chunk_data
                break
        self.logger.debug('    target_chunk_data:' + str(target_chunk_data))

        # チャンクデータを元にバイナリ情報を取得
        external_data = None
        if target_chunk_data is not None:
            external_data = self._get_external_data_from_chunk(
                target_chunk_data,
                self.binary_data,
            )
        if external_data is not None:
            self.logger.debug('    external_data size:' +
                              str(len(external_data)))

        return external_data

    def _get_external_id_from_chunk(self, chunk_data, binary_data):
        offset = chunk_data['chunk_start_position']

        # 16バイト：読み飛ばし
        offset += 16

        # ビッグエンディアン8バイト：チャンクサイズ
        chunk_size = struct.unpack_from('>Q', binary_data, offset)[0]
        offset += 8

        # External ID 読み出し
        external_id = struct.unpack_from(
            str(chunk_size) + 's', binary_data, offset)[0]
        external_id = external_id.decode()

        return external_id

    def _get_external_data_from_chunk(self, chunk_data, binary_data):
        offset = chunk_data['chunk_start_position']

        # 16バイト：読み飛ばし
        offset += 16

        # ビッグエンディアン8バイト：チャンクサイズ
        chunk_size = struct.unpack_from('>Q', binary_data, offset)[0]
        offset += 8

        # External ID 読み出し
        external_id = struct.unpack_from(
            str(chunk_size) + 's', binary_data, offset)[0]
        external_id = external_id.decode()
        offset += chunk_size

        # ビッグエンディアン8バイト：Externalデータサイズ(読み飛ばし)
        # external_data_size = struct.unpack_from('>Q', binary_data, offset)[0]
        offset += 8

        external_data = bytes([])
        while offset < chunk_data['chunk_end_position']:
            block_start_position = offset

            # ビッグエンディアン4バイト：サイズ01
            size_01 = struct.unpack_from('>L', binary_data, offset)[0]
            offset += 4

            # ビッグエンディアン4バイト：サイズ02
            size_02 = struct.unpack_from('>L', binary_data, offset)[0]
            offset += 4

            # データブロック名とサイズを設定
            block_name_len = None
            block_data_len = None
            if size_02 == 0x0042006C:  # "Bl"
                block_name_len = size_01
                block_data_len = 0
                offset = block_start_position + 4
            else:
                block_name_len = size_02
                block_data_len = size_01

            # データブロック名取得
            block_name = '<toobig>'
            if block_name_len < 256:
                block_name = struct.unpack_from(
                    str(block_name_len * 2) + 's', binary_data, offset)[0]
                block_name = block_name.decode('utf-16-be')
                offset += block_name_len * 2
            else:
                offset = block_name_len * 2

            # データブロック
            block_start_position = offset
            block_end_position = block_start_position + block_data_len

            block_len = 0
            if block_name == 'BlockDataBeginChunk':
                # ビッグエンディアン4バイト：ブロックインデックス（読み飛ばし）
                # block_index = struct.unpack_from('>L', binary_data, offset)[0]
                offset += 4

                # ビッグエンディアン4バイト：ブロックサイズ（非圧縮）
                block_uncompressed_size = struct.unpack_from(
                    '>L', binary_data, offset)[0]
                offset += 4

                # ビッグエンディアン4バイト：ブロック幅
                # block_width = struct.unpack_from('>L', binary_data, offset)[0]
                offset += 4

                # ビッグエンディアン4バイト：ブロック高さ
                # block_height = struct.unpack_from('>L', binary_data, offset)[0]
                offset += 4

                # ビッグエンディアン4バイト：ブロック存在有無
                exist_flag = struct.unpack_from('>L', binary_data, offset)[0]
                offset += 4

                if exist_flag > 0:
                    # ビッグエンディアン4バイト：ブロック長さ
                    block_len = struct.unpack_from('>L', binary_data,
                                                   offset)[0]
                    offset += 4

                    # ビッグエンディアン4バイト：ブロック長さ2
                    block_len_2 = struct.unpack_from('<L', binary_data,
                                                     offset)[0]
                    offset += 4

                    if block_len_2 < block_len - 4:
                        self.logger.error('_get_external_data_from_chunk()')
                        self.logger.error('    Error:block length')

                    # ブロックデータ取得、解凍
                    block_zlib_data = binary_data[offset:offset + block_len_2]
                    block_data = zlib.decompress(block_zlib_data)

                    # ブロックデータ追加
                    external_data += block_data

                    if len(block_data) != block_uncompressed_size:
                        self.logger.error('_get_external_data_from_chunk()')
                        self.logger.error(
                            '    Error:Mismatch uncompressed size')

                    block_end_position = block_start_position + 24 + block_len
                else:
                    # ブロックデータ追加
                    external_data += bytes(block_uncompressed_size)

                    block_end_position = block_start_position + 20
            elif block_name == 'BlockStatus' or block_name == 'BlockCheckSum':
                # ビッグエンディアン4バイト：i0（読み飛ばし）
                # i0 = struct.unpack_from('>L', binary_data, offset)[0]
                offset += 4

                # ビッグエンディアン4バイト：ブロックサイズ（非圧縮）
                block_uncompressed_size = struct.unpack_from(
                    '>L', binary_data, offset)[0]
                offset += 4

                # ビッグエンディアン4バイト：ブロック幅（読み飛ばし）
                # block_width = struct.unpack_from('>L', binary_data, offset)[0]
                offset += 4

                # ビッグエンディアン4バイト：ブロック高さ（読み飛ばし）
                # block_height = struct.unpack_from('>L', binary_data, offset)[0]
                offset += 4

                # ビッグエンディアン4バイト：i4（読み飛ばし）
                # i4 = struct.unpack_from('>L', binary_data, offset)[0]
                offset += 4

                # ビッグエンディアン4バイト：i5（読み飛ばし）
                # i5 = struct.unpack_from('>L', binary_data, offset)[0]
                offset += 4

                block_end_position = block_start_position + 24 + block_len
            elif block_name == 'BlockDataEndChunk':
                pass

            offset = block_end_position

        return external_data

    def _get_image_from_external_data(
        self,
        external_data,
        image_width,
        image_height,
    ):
        self.logger.debug('_get_image_from_external_data()')

        # 各種定数値
        pixel_size = 4
        bgr_composite_block_size = 256 * 320 * pixel_size
        block_size = 256 * 256
        blocks_per_row = int((image_height + 255) / 256)
        blocks_per_column = int((image_width + 255) / 256)
        padded_width = blocks_per_column * 256
        padded_height = blocks_per_row * 256

        grayscale_expected_size = padded_width * padded_height
        bgr_expected_size = padded_width * padded_height * (pixel_size + 1)

        self.logger.debug('    pixel_size:' + str(pixel_size))
        self.logger.debug('    bgr_composite_block_size:' +
                          str(bgr_composite_block_size))
        self.logger.debug('    block_size:' + str(block_size))
        self.logger.debug('    blocks_per_row:' + str(blocks_per_row))
        self.logger.debug('    blocks_per_column:' + str(blocks_per_column))
        self.logger.debug('    padded_width:' + str(padded_width))
        self.logger.debug('    padded_height:' + str(padded_height))
        self.logger.debug('    grayscale_expected_size:' +
                          str(grayscale_expected_size))
        self.logger.debug('    bgr_expected_size:' + str(bgr_expected_size))

        # グレースケール画像チェック
        # ToDo：グレースケール画像対応
        if len(external_data) == grayscale_expected_size:
            self.logger.error('_get_image_from_external_data()')
            self.logger.error('    Unsupport grayscale image')
        # サイズチェック
        elif len(external_data) != bgr_expected_size:
            self.logger.error('_get_image_from_external_data()')
            self.logger.error('    bgr_expected_size:Mismatch Size')

        # External Data を 画像に変換
        bgr_image, alpha_image = self._externaldata2image(
            external_data,
            block_size,
            blocks_per_row,
            blocks_per_column,
            bgr_composite_block_size,
        )

        # パディングを削除
        if bgr_image is not None:
            bgr_image = bgr_image[:image_height, :image_width]
        if alpha_image is not None:
            alpha_image = alpha_image[:image_height, :image_width]

        return bgr_image, alpha_image

    def _externaldata2image(
        self,
        external_data,
        block_size,
        blocks_per_row,
        blocks_per_column,
        bgr_composite_block_size,
    ):
        # 各ブロックデータの画像を保持するリスト
        bgra_block_list = [[None] * blocks_per_column
                           for _ in range(blocks_per_row)]
        alpha_block_list = [[None] * blocks_per_column
                            for _ in range(blocks_per_row)]

        # External Data(バイト列) を Numpy Array 形式に変換
        external_data = np.frombuffer(external_data, dtype=np.uint8)

        for block_index in range(blocks_per_row * blocks_per_column):
            # ブロックデータのアドレスと位置を算出
            block_address = block_index * bgr_composite_block_size
            block_x = int(block_index % blocks_per_column)
            block_y = int(block_index / blocks_per_column)

            # 各ブロックデータを取得
            block = external_data[block_address:block_address +
                                  bgr_composite_block_size]
            alpha_block = block[0:block_size]
            bgra_block = block[block_size:]

            # アルファ画像をリシェイプしてリストに追加
            alpha_block = alpha_block.reshape(256, 256)
            alpha_block_list[block_y][block_x] = alpha_block

            # 画像をリシェイプしてリストに追加
            bgra_block = bgra_block.reshape(256, 256, 4)
            bgra_block_list[block_y][block_x] = bgra_block

        # アルファ画像を連結
        alpha_image = None
        for block_y in range(blocks_per_row):
            temp_alpha = None
            for block_x in range(blocks_per_column):
                if temp_alpha is None:
                    temp_alpha = alpha_block_list[block_y][block_x]
                else:
                    temp_alpha = np.hstack(
                        [temp_alpha, alpha_block_list[block_y][block_x]])
            if alpha_image is None:
                alpha_image = temp_alpha
            else:
                alpha_image = np.vstack([alpha_image, temp_alpha])

        # 画像を連結
        bgra_image = None
        for block_y in range(blocks_per_row):
            temp_rgba = None
            for block_x in range(blocks_per_column):
                if temp_rgba is None:
                    temp_rgba = bgra_block_list[block_y][block_x]
                else:
                    temp_rgba = np.hstack(
                        [temp_rgba, bgra_block_list[block_y][block_x]])
            if bgra_image is None:
                bgra_image = temp_rgba
            else:
                bgra_image = np.vstack([bgra_image, temp_rgba])
        bgr_image = np.delete(bgra_image, 3, 2)

        return bgr_image, alpha_image

    def set_debug_level(
            self,
            log_filename=None,
            debug_level='WARNING',  # 'DEBUG', 'INFO', 'ERROR', 'CRITICAL'
    ):
        if debug_level == 'DEBUG':
            self.logger.setLevel(logging.DEBUG)
            logging.basicConfig(filename=log_filename, level=logging.DEBUG)
        elif debug_level == 'INFO':
            self.logger.setLevel(logging.INFO)
            logging.basicConfig(filename=log_filename, level=logging.INFO)
        elif debug_level == 'WARNING':
            self.logger.setLevel(logging.WARNING)
        elif debug_level == 'ERROR':
            self.logger.setLevel(logging.ERROR)
        elif debug_level == 'CRITICAL':
            self.logger.setLevel(logging.CRITICAL)


if __name__ == '__main__':
    csp_tool = CspTool(
        'test.clip',
        # log_filename='log.txt',
        debug_level='WARNING',  # 'DEBUG'
    )

    # レイヤー情報取得
    layer_list = csp_tool.get_layer_list()
    for layer_data in layer_list:
        test_string = layer_data['layer_name']
        test_string += ' (Canvas ID:' + str(layer_data['canvas_id'])
        test_string += ' Layer ID:' + str(layer_data['main_id']) + ')'
        print(test_string)

    # ラスターデータ取得
    bgr_image, alpha_image, bgra_image = csp_tool.get_raster_data(
        canvas_id=1,
        layer_id=3,
    )

    # 表示確認
    import cv2
    if bgr_image is not None:
        cv2.imshow('Clip Studio Paint File:Image', bgr_image)
        cv2.imshow('Clip Studio Paint File:Alpha', alpha_image)
        cv2.waitKey(-1)
    else:
        print('Layer does not contain image.')
